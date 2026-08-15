import logging
import os
import uuid
from contextlib import asynccontextmanager

import inngest
import inngest.fast_api
import logfire
from dotenv import load_dotenv
from fastapi import Depends
from fastapi import FastAPI
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.database import get_db
from app.models import Film

load_dotenv()

# --- Logfire: works with LOGFIRE_TOKEN (FastAPI Cloud injects it) or falls back to console ---
# If no token, traces go to local console only (no network).
logfire.configure(
    service_name="splicer",
    send_to_logfire="if-token-present",
    console=logfire.ConsoleOptions(colors="auto", include_timestamps=True),
)
logger = logging.getLogger("uvicorn")
logger.setLevel(logging.INFO)

# Instrument SQLAlchemy if engine exists
if engine is not None:
    try:
        logfire.instrument_sqlalchemy(engine=engine)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify DB connectivity (Neon pooled)
    if engine is not None:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logfire.info("neon: connected", engine=str(engine.url).split("@")[-1][:40])
        except Exception as e:
            logfire.warn("neon: startup check failed", error=str(e))
    yield


# --- FastAPI ---
app = FastAPI(
    title="Splicer",
    description="Movie recap pipeline API — concurrent proxy, scenes, safety, script, TTS, assemble",
    version="0.1.0",
    lifespan=lifespan,
)

logfire.instrument_fastapi(app)
logfire.instrument_pydantic()

# --- Inngest ---
# Inngest requires a signing key. For local dev we can use a dummy.
_inngest_signing_key = os.getenv("INNGEST_SIGNING_KEY") or (
    "signkey-test-fake-not-for-prod" if os.getenv("INNGEST_DEV") else None
)
_inngest_event_key = os.getenv("INNGEST_EVENT_KEY")

inngest_client = inngest.Inngest(
    app_id="splicer",
    logger=logger,
    is_production=not bool(os.getenv("INNGEST_DEV")),
    signing_key=_inngest_signing_key,
    event_key=_inngest_event_key,
)


# Example durable function — replace with pipeline stages
@inngest_client.create_function(
    fn_id="hello-pipeline",
    trigger=inngest.TriggerEvent(event="splicer/hello"),
    concurrency=[inngest.Concurrency(limit=3)],  # dev: 3 concurrent as locked
)
async def hello_pipeline(ctx: inngest.Context) -> dict:
    """Skeleton: durable, retried, observable step fan-out."""
    logfire.info("hello_pipeline triggered", event=ctx.event.data)
    film_title = ctx.event.data.get("film_title", "I Am Legend")

    # Each step is durable, retried, and shows in Inngest UI + Logfire trace
    async def _fetch():
        return {"title": film_title, "director": "Francis Lawrence", "year": 2007}

    async def _validate():
        return {"ok": True, "film": {"title": film_title}}

    scene = await ctx.step.run("fetch-film-metadata", _fetch)
    validated = await ctx.step.run("validate", _validate)
    # fan-out example for 1FPS work (Qwen-VL + Shieldstral in parallel later)
    # results = await ctx.step.parallel([...])

    ctx.logger.info(f"Validated {film_title}: {validated}")
    return {"status": "ok", "film": scene, "validated": validated}


# Proxy pipeline — durable transcode 480p via RunPod volume or S3 fallback
@inngest_client.create_function(
    fn_id="proxy-film",
    trigger=inngest.TriggerEvent(event="film/proxy.requested"),
    concurrency=[inngest.Concurrency(limit=3)],  # locked to 3 for dev
    retries=3,
)
async def proxy_film(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", "unknown"))
    s3_key = str(ctx.event.data.get("s3_key", ""))
    asset_id = str(ctx.event.data.get("asset_id", ""))
    proxy_key = (
        s3_key.replace("1080p", "480p_proxy")
        if "1080p" in s3_key
        else s3_key.rsplit(".", 1)[0] + "_480p_proxy.mp4"
    )
    with logfire.span("proxy_film", film_id=film_id):
        logfire.info("proxy requested", film_id=film_id, s3_key=s3_key, proxy_key=proxy_key)

        async def _transcode():
            from app.proxy import transcode_480p_s3

            # create job mirror queued
            try:
                import uuid as _uuid

                from app.database import SessionLocal
                from app.models import Job

                if asset_id:
                    db = SessionLocal()
                    try:
                        # find film's video or create job with film_id as video_id fallback
                        job = Job(
                            id=_uuid.uuid4(),
                            kind="proxy",  # type: ignore
                            status="running",  # type: ignore
                            inngest_run_id=str(ctx.run_id) if hasattr(ctx, "run_id") else None,
                        )
                        # try to attach to first video for film
                        try:
                            from app.models import Video

                            vid = db.query(Video).filter(Video.film_id == film_id).first()
                            if vid:
                                job.video_id = vid.id  # type: ignore
                        except Exception:
                            pass
                        db.add(job)
                        db.commit()
                    finally:
                        db.close()
            except Exception as e:
                logfire.warn("job mirror create failed", error=str(e))
            result = transcode_480p_s3(s3_key, proxy_key)
            # mark asset and job completed, verify via S3 list
            try:
                from app.database import SessionLocal
                from app.models import Asset

                db2 = SessionLocal()
                try:
                    # create or update proxy asset pointer
                    existing = db2.query(Asset).filter(Asset.s3_key == proxy_key).first()
                    if not existing:
                        # find film_id from source asset
                        src = db2.query(Asset).filter(Asset.s3_key == s3_key).first()
                        fid = src.film_id if src else film_id
                        asset = Asset(
                            film_id=fid,  # type: ignore
                            kind="proxy_480p",  # type: ignore
                            runpod_volume_id=result.get("bucket"),
                            s3_key=proxy_key,
                            s3_endpoint=os.getenv(
                                "AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"
                            ),
                            datacenter=os.getenv("AWS_S3_REGION", "EU-RO-1"),
                            size_bytes=None,
                            status="available",
                        )
                        db2.add(asset)
                    else:
                        existing.status = "available"  # type: ignore
                    # verify via S3 list
                    try:
                        from app.s3 import VOLUME_ID
                        from app.s3 import get_s3_client

                        s3 = get_s3_client()
                        lst = s3.list_objects_v2(
                            Bucket=result.get("bucket") or VOLUME_ID, Prefix=proxy_key
                        )
                        if lst.get("KeyCount", 0) > 0:
                            for obj in lst.get("Contents", []):
                                if obj["Key"] == proxy_key:
                                    # update size
                                    if existing:
                                        existing.size_bytes = int(obj["Size"])  # type: ignore
                                    else:
                                        asset.size_bytes = int(obj["Size"])  # type: ignore
                                    break
                    except Exception as ex:
                        logfire.warn("proxy verify list failed", error=str(ex))
                    db2.commit()
                finally:
                    db2.close()
            except Exception as e:
                logfire.warn("proxy asset persist failed", error=str(e))
            return {"s3_key": s3_key, "proxy_key": proxy_key, "result": result}

        steps = await ctx.step.run("transcode-480p", _transcode)
        logfire.info("proxy completed", proxy_key=proxy_key)
        return steps


# Additional durable stages — KB, audio, VLM, script, TTS/assemble, safety (all concurrency 3 dev)
@inngest_client.create_function(
    fn_id="enrich-kb",
    trigger=inngest.TriggerEvent(event="film/kb.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def enrich_kb(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    with logfire.span("enrich_kb", film_id=film_id):

        async def _kb():
            from app.kb import enrich_film_metadata

            return enrich_film_metadata(film_id)

        return await ctx.step.run("tmdb-omdb-enrich", _kb)


@inngest_client.create_function(
    fn_id="enrich-audio",
    trigger=inngest.TriggerEvent(event="film/audio.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def enrich_audio(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    s3_key = str(ctx.event.data.get("s3_key", ""))
    srt_key = str(ctx.event.data.get("srt_key", "")) or None
    with logfire.span("enrich_audio", film_id=film_id):

        async def _audio():
            from app.audio import enrich_audio_for_film

            return enrich_audio_for_film(film_id, s3_key, srt_key)

        return await ctx.step.run("audio-enrich", _audio)


@inngest_client.create_function(
    fn_id="hierarchical-vlm",
    trigger=inngest.TriggerEvent(event="film/vlm.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def hierarchical_vlm(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    s3_key = str(ctx.event.data.get("s3_key", ""))
    audio_key = str(ctx.event.data.get("audio_enrich_key", "")) or None
    with logfire.span("vlm", film_id=film_id):

        async def _vlm():
            from app.vlm import run_hierarchical_vlm

            return run_hierarchical_vlm(film_id, s3_key, audio_key)

        return await ctx.step.run("vlm-hierarchical", _vlm)


@inngest_client.create_function(
    fn_id="generate-script",
    trigger=inngest.TriggerEvent(event="film/script.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def generate_script(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    video_id = str(ctx.event.data.get("video_id", "")) or None
    with logfire.span("script", film_id=film_id):

        async def _script():
            from app.script import generate_script_for_film

            return generate_script_for_film(film_id, video_id)

        return await ctx.step.run("openrouter-script", _script)


@inngest_client.create_function(
    fn_id="tts-assemble",
    trigger=inngest.TriggerEvent(event="film/assemble.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def tts_assemble(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    video_id = str(ctx.event.data.get("video_id", "")) or None
    with logfire.span("assemble", film_id=film_id):

        async def _assemble():
            from app.assemble import tts_and_assemble

            return tts_and_assemble(film_id, video_id)

        return await ctx.step.run("tts-blender-assemble", _assemble)


@inngest_client.create_function(
    fn_id="safety-final",
    trigger=inngest.TriggerEvent(event="film/safety.requested"),
    concurrency=[inngest.Concurrency(limit=3)],
    retries=2,
)
async def safety_final(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", ""))
    final_key = str(ctx.event.data.get("final_s3_key", "")) or None
    with logfire.span("safety", film_id=film_id):

        async def _safety():
            from app.safety import run_safety_on_final

            return run_safety_on_final(film_id, final_key)

        return await ctx.step.run("shieldstral-safety", _safety)


inngest.fast_api.serve(
    app,
    inngest_client,
    [
        hello_pipeline,
        proxy_film,
        enrich_kb,
        enrich_audio,
        hierarchical_vlm,
        generate_script,
        tts_assemble,
        safety_final,
    ],
)


# --- Pydantic schemas ---
class HelloIn(BaseModel):
    film_title: str = "I Am Legend"


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


class FilmIn(BaseModel):
    title: str
    year: int | None = None
    director: str | None = None


class FilmOut(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None
    director: str | None

    class Config:
        from_attributes = True


class UploadInitIn(BaseModel):
    film_id: uuid.UUID
    filename: str
    size_bytes: int
    content_type: str = "video/mp4"
    part_size_bytes: int = 64 * 1024 * 1024  # 64MB default, ~24 parts for 1.5GB


class UploadInitOut(BaseModel):
    upload_id: uuid.UUID  # == asset.id
    film_id: uuid.UUID
    s3_key: str
    s3_endpoint: str
    bucket: str
    uploadId: str  # S3 multipart UploadId
    presigned_urls: list[str]
    part_size_bytes: int
    part_count: int
    expires_in: int = 3600


class UploadCompleteIn(BaseModel):
    uploadId: str
    parts: list[dict]  # [{"ETag": "...", "PartNumber": 1}, ...]
    s3_key: str | None = None


class UploadCompleteOut(BaseModel):
    status: str
    s3_key: str
    size_bytes: int | None
    etag: str | None = None


# --- Routes ---
@app.get("/", response_model=HealthOut, tags=["system"])
def root():
    logfire.info("root hit")
    return HealthOut(status="ok", service="splicer", version="0.1.0")


@app.get("/health", response_model=HealthOut, tags=["system"])
def health():
    return HealthOut(status="ok", service="splicer", version="0.1.0")


@app.get("/health/db", tags=["system"])
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        # Count films as sanity
        count = db.query(Film).count()
        return {"status": "ok", "neon": "connected", "films": count}
    except Exception as e:
        logfire.error("db health failed", error=str(e))
        raise HTTPException(status_code=503, detail=f"db unavailable: {e}")


@app.post("/api/films", response_model=FilmOut, tags=["films"])
def create_film(data: FilmIn, db: Session = Depends(get_db)):
    logfire.info("create_film", title=data.title)
    film = Film(title=data.title, year=data.year, director=data.director)
    db.add(film)
    db.commit()
    db.refresh(film)
    return film


@app.get("/api/films", response_model=list[FilmOut], tags=["films"])
def list_films(db: Session = Depends(get_db)):
    return db.query(Film).order_by(Film.created_at.desc()).limit(50).all()


@app.post("/api/uploads/init", response_model=UploadInitOut, tags=["uploads"])
def init_upload(data: UploadInitIn, db: Session = Depends(get_db)):
    """Mint presigned multipart URLs for direct-to-RunPod S3 upload (parallel, 3×). No bytes via FastAPI."""
    import math

    from app.models import Asset
    from app.s3 import S3_ENDPOINT
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from app.s3 import s3_key_for_film

    # Validate film exists
    film = db.query(Film).filter(Film.id == data.film_id).first()
    if not film:
        raise HTTPException(status_code=404, detail="film not found")

    # Validate size
    if data.size_bytes <= 0:
        raise HTTPException(status_code=400, detail="size_bytes must be > 0")
    part_count = max(1, math.ceil(data.size_bytes / data.part_size_bytes))
    if part_count > 10000:
        raise HTTPException(status_code=400, detail="too many parts — increase part_size_bytes")

    s3_key = s3_key_for_film(str(data.film_id), data.filename)
    s3 = get_s3_client()
    bucket = VOLUME_ID

    with logfire.span(
        "upload.init", film_id=str(data.film_id), s3_key=s3_key, part_count=part_count
    ):
        try:
            from app.s3 import create_multipart_upload
            from app.s3 import presigned_part_urls

            upload_id = create_multipart_upload(s3, bucket, s3_key)
            presigned = presigned_part_urls(s3, bucket, s3_key, upload_id, part_count)
        except Exception as e:
            logfire.error("s3 create_multipart failed", error=str(e))
            raise HTTPException(status_code=502, detail=f"S3 init failed: {e}") from e

        # Persist asset as uploading — size unknown until complete, store part info in codec field temp
        asset = Asset(
            film_id=data.film_id,
            kind="source_1080p",
            runpod_volume_id=bucket,
            s3_key=s3_key,
            s3_endpoint=S3_ENDPOINT,
            datacenter=os.getenv("AWS_S3_REGION", "EU-RO-1"),
            size_bytes=data.size_bytes,
            status="uploading",
        )
        # Store uploadId transiently in codec (not ideal but avoids migration for slice)
        asset.codec = upload_id  # reuse codec column for multipart UploadId during upload
        db.add(asset)
        db.commit()
        db.refresh(asset)
        logfire.info("upload.init minted", upload_id=str(asset.id), s3_key=s3_key, parts=part_count)

        return UploadInitOut(
            upload_id=asset.id,
            film_id=data.film_id,
            s3_key=s3_key,
            s3_endpoint=S3_ENDPOINT,
            bucket=bucket,
            uploadId=upload_id,
            presigned_urls=presigned,
            part_size_bytes=data.part_size_bytes,
            part_count=part_count,
        )


@app.post("/api/uploads/{upload_id}/complete", response_model=UploadCompleteOut, tags=["uploads"])
def complete_upload(upload_id: uuid.UUID, data: UploadCompleteIn, db: Session = Depends(get_db)):
    """Client calls after PUTting all parts to presigned URLs — verifies via S3 HeadObject, flips to available, fires Inngest fan-out (3)."""
    from app.models import Asset
    from app.s3 import VOLUME_ID
    from app.s3 import complete_multipart_upload
    from app.s3 import get_s3_client
    from app.s3 import head_object_safe

    asset = db.query(Asset).filter(Asset.id == upload_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="upload asset not found")
    s3_key = data.s3_key or asset.s3_key
    bucket = asset.runpod_volume_id or VOLUME_ID
    uploadId = data.uploadId or asset.codec

    if not uploadId:
        raise HTTPException(status_code=400, detail="missing uploadId — provide in body or init")

    s3 = get_s3_client()
    with logfire.span("upload.complete", upload_id=str(upload_id), s3_key=s3_key):
        try:
            # Verify parts sorted
            parts = sorted(data.parts, key=lambda p: p["PartNumber"])
            if not parts:
                raise HTTPException(
                    status_code=400, detail="parts array empty — need ETags from S3 PUT responses"
                )
            complete_multipart_upload(s3, bucket, s3_key, uploadId, parts)
        except HTTPException:
            raise
        except Exception as e:
            logfire.error("s3 complete failed", error=str(e))
            raise HTTPException(status_code=502, detail=f"S3 complete failed: {e}") from e

        # Verify availability
        head = head_object_safe(s3, bucket, s3_key)
        if not head:
            raise HTTPException(
                status_code=502, detail="S3 HeadObject failed after complete — object not found"
            )
        size = int(head.get("ContentLength", asset.size_bytes or 0))
        etag = head.get("ETag", "").strip('"')

        asset.size_bytes = size
        asset.status = "available"
        asset.codec = None  # clear transient UploadId
        db.commit()

        # Fire Inngest for downstream proxy (3 concurrent) — non-blocking, log warn if dev server down
        try:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(
                    inngest_client.send(
                        inngest.Event(
                            name="film/proxy.requested",
                            data={
                                "film_id": str(asset.film_id),
                                "s3_key": s3_key,
                                "asset_id": str(asset.id),
                            },
                        )
                    )
                )
            else:
                # Fallback: try sync send in background thread (best-effort)
                import threading

                def _send():
                    try:
                        import asyncio as _aio

                        _aio.run(
                            inngest_client.send(
                                inngest.Event(
                                    name="film/proxy.requested",
                                    data={
                                        "film_id": str(asset.film_id),
                                        "s3_key": s3_key,
                                        "asset_id": str(asset.id),
                                    },
                                )
                            )
                        )
                    except Exception as ex:
                        logfire.warn("inngest proxy trigger failed", error=str(ex))

                threading.Thread(target=_send, daemon=True).start()

            logfire.info("proxy requested", film_id=str(asset.film_id), s3_key=s3_key)
        except Exception as e:
            logfire.warn("inngest send on complete failed", error=str(e))

        return UploadCompleteOut(status="available", s3_key=s3_key, size_bytes=size, etag=etag)


@app.get("/api/uploads/{upload_id}", tags=["uploads"])
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.models import Asset

    asset = db.query(Asset).filter(Asset.id == upload_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="upload not found")
    # Live HeadObject check for staleness
    try:
        from app.s3 import VOLUME_ID
        from app.s3 import get_s3_client
        from app.s3 import head_object_safe

        s3 = get_s3_client()
        head = head_object_safe(s3, str(asset.runpod_volume_id or VOLUME_ID), str(asset.s3_key))
        live = {
            "exists": head is not None,
            "size": int(head["ContentLength"]) if head else None,
            "etag": head.get("ETag") if head else None,
        }
    except Exception as e:
        live = {"exists": None, "error": str(e)}
    return {
        "id": str(asset.id),
        "film_id": str(asset.film_id),
        "s3_key": str(asset.s3_key),
        "status": asset.status,
        "size_bytes": asset.size_bytes,
        "live": live,
    }


@app.post("/api/uploads", tags=["uploads"])
async def upload_direct(
    film_id: uuid.UUID,
    file: UploadFile = File(...),
    kind: str = "source_1080p",
    db: Session = Depends(get_db),
):
    """Direct streaming upload to RunPod S3 (fallback for presigned 401, still parallel 3× via async)."""
    from app.models import Asset
    from app.s3 import S3_ENDPOINT
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from app.s3 import s3_key_for_film

    # Validate kind
    allowed = {"source_1080p", "proxy_480p", "subtitle", "thumbnail", "final_1080p"}
    if kind not in allowed:
        raise HTTPException(status_code=400, detail=f"kind must be one of {allowed}")

    film = db.query(Film).filter(Film.id == film_id).first()
    if not film:
        raise HTTPException(status_code=404, detail="film not found")

    s3_key = s3_key_for_film(str(film_id), file.filename or "upload.bin")
    bucket = VOLUME_ID
    s3 = get_s3_client()

    # Stream to S3 without buffering whole file in memory — use multipart via boto3
    # FastAPI UploadFile is SpooledTemporaryFile, we can stream chunks
    import tempfile

    with logfire.span("upload.direct", film_id=str(film_id), s3_key=s3_key, kind=kind):
        tmp_path = None
        try:
            # Write to temp file to get size and allow boto3 streaming
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
                # Stream copy
                while True:
                    chunk = await file.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
            local_size = os.path.getsize(tmp_path)
            # Upload via boto3 (handles multipart automatically for 1.5GB)
            s3.upload_file(tmp_path, bucket, s3_key)
            # HeadObject on RunPod S3 can 403 even when object exists (list works) — fallback
            size = local_size
            try:
                head = s3.head_object(Bucket=bucket, Key=s3_key)
                size = int(head.get("ContentLength", local_size))
            except Exception as e:
                logfire.warn("head_object 403 fallback to local size", error=str(e), s3_key=s3_key)
                # Verify via list instead
                try:
                    lst = s3.list_objects_v2(Bucket=bucket, Prefix=s3_key)
                    if lst.get("KeyCount", 0) > 0:
                        for obj in lst.get("Contents", []):
                            if obj["Key"] == s3_key:
                                size = int(obj["Size"])
                                break
                except Exception as ex2:
                    logfire.warn("list fallback also failed", error=str(ex2))
            # Persist asset
            asset = Asset(
                film_id=film_id,
                kind=kind,  # type: ignore
                runpod_volume_id=bucket,
                s3_key=s3_key,
                s3_endpoint=S3_ENDPOINT,
                datacenter=os.getenv("AWS_S3_REGION", "EU-RO-1"),
                size_bytes=size,
                status="available",
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            logfire.info(
                "upload.direct done", film_id=str(film_id), s3_key=s3_key, size=size, kind=kind
            )
            # Fire Inngest proxy (best-effort)
            try:
                import asyncio
                import threading

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    loop.create_task(
                        inngest_client.send(
                            inngest.Event(
                                name="film/proxy.requested",
                                data={
                                    "film_id": str(film_id),
                                    "s3_key": s3_key,
                                    "asset_id": str(asset.id),
                                },
                            )
                        )
                    )
                else:

                    def _send():
                        try:
                            import asyncio as _aio

                            _aio.run(
                                inngest_client.send(
                                    inngest.Event(
                                        name="film/proxy.requested",
                                        data={
                                            "film_id": str(film_id),
                                            "s3_key": s3_key,
                                            "asset_id": str(asset.id),
                                        },
                                    )
                                )
                            )
                        except Exception as ex:
                            logfire.warn("inngest proxy trigger failed", error=str(ex))

                    threading.Thread(target=_send, daemon=True).start()
            except Exception as e:
                logfire.warn("inngest send on direct failed", error=str(e))

            return {
                "id": str(asset.id),
                "film_id": str(film_id),
                "s3_key": s3_key,
                "status": "available",
                "size_bytes": size,
                "bucket": bucket,
                "s3_endpoint": S3_ENDPOINT,
            }
        except Exception as e:
            logfire.error("direct upload failed", error=str(e))
            raise HTTPException(status_code=502, detail=f"S3 upload failed: {e}") from e
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


@app.post("/api/hello", tags=["pipeline"])
async def trigger_hello(data: HelloIn):
    """Enqueue a durable hello run (observable, retried). Returns immediately."""
    logfire.info("enqueue hello", film_title=data.film_title)
    try:
        await inngest_client.send(inngest.Event(name="splicer/hello", data=data.model_dump()))
        return JSONResponse({"queued": True, "event": "splicer/hello", "data": data.model_dump()})
    except Exception as e:
        logfire.warn("inngest send failed — dev server not running?", error=str(e))
        # In dev without `inngest dev` running, still return 202 so the API is testable
        return JSONResponse(
            {
                "queued": False,
                "warning": "Inngest dev server not reachable — start `inngest dev -u http://localhost:8000/api/inngest`",
                "error": str(e),
                "data": data.model_dump(),
            },
            status_code=202,
        )


@app.get("/api/inngest/health", tags=["system"])
def inngest_health():
    return {"inngest_app_id": inngest_client.app_id, "is_production": inngest_client.is_production}


# --- Pipeline orchestration endpoints (thin wrappers over Inngest, all concurrency 3) ---
class EnrichIn(BaseModel):
    film_id: uuid.UUID
    title: str | None = None
    imdb_id: str | None = None


class AudioEnrichIn(BaseModel):
    film_id: uuid.UUID
    s3_key: str
    srt_key: str | None = None


class VlmIn(BaseModel):
    film_id: uuid.UUID
    s3_key: str
    audio_enrich_key: str | None = None


class ScriptIn(BaseModel):
    film_id: uuid.UUID
    video_id: uuid.UUID | None = None


class AssembleIn(BaseModel):
    film_id: uuid.UUID
    video_id: uuid.UUID | None = None


class SafetyIn(BaseModel):
    film_id: uuid.UUID
    final_s3_key: str | None = None


@app.post("/api/films/{film_id}/enrich", tags=["pipeline"])
async def enrich_film(film_id: uuid.UUID):
    logfire.info("enqueue kb enrich", film_id=str(film_id))
    try:
        await inngest_client.send(
            inngest.Event(name="film/kb.requested", data={"film_id": str(film_id)})
        )
        return {"queued": True, "event": "film/kb.requested", "film_id": str(film_id)}
    except Exception as e:
        logfire.warn("inngest kb send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.post("/api/films/{film_id}/enrich-audio", tags=["pipeline"])
async def enrich_film_audio(film_id: uuid.UUID, data: AudioEnrichIn | None = None):
    # resolve s3_key/srt_key from DB if not provided
    s3_key = data.s3_key if data and data.s3_key else ""
    srt_key = data.srt_key if data and data.srt_key else None
    if not s3_key:
        from app.database import SessionLocal
        from app.models import Asset

        db = SessionLocal()
        try:
            src = (
                db.query(Asset)
                .filter(Asset.film_id == film_id, Asset.kind == "source_1080p")
                .first()
            )  # type: ignore
            if src:
                s3_key = src.s3_key  # type: ignore
            sub = db.query(Asset).filter(Asset.film_id == film_id, Asset.kind == "subtitle").first()  # type: ignore
            if sub:
                srt_key = sub.s3_key  # type: ignore
        finally:
            db.close()
    logfire.info("enqueue audio enrich", film_id=str(film_id), s3_key=s3_key)
    try:
        await inngest_client.send(
            inngest.Event(
                name="film/audio.requested",
                data={"film_id": str(film_id), "s3_key": s3_key, "srt_key": srt_key or ""},
            )
        )
        return {"queued": True, "event": "film/audio.requested", "s3_key": s3_key}
    except Exception as e:
        logfire.warn("inngest audio send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.post("/api/films/{film_id}/vlm", tags=["pipeline"])
async def trigger_vlm(film_id: uuid.UUID, data: VlmIn | None = None):
    s3_key = data.s3_key if data and data.s3_key else ""
    audio_key = (
        data.audio_enrich_key
        if data and data.audio_enrich_key
        else f"films/{film_id}/audio_enrich.json"
    )
    if not s3_key:
        from app.database import SessionLocal
        from app.models import Asset

        db = SessionLocal()
        try:
            src = (
                db.query(Asset)
                .filter(Asset.film_id == film_id, Asset.kind == "source_1080p")
                .first()
            )  # type: ignore
            if src:
                s3_key = src.s3_key  # type: ignore
        finally:
            db.close()
    logfire.info("enqueue vlm", film_id=str(film_id), s3_key=s3_key)
    try:
        await inngest_client.send(
            inngest.Event(
                name="film/vlm.requested",
                data={"film_id": str(film_id), "s3_key": s3_key, "audio_enrich_key": audio_key},
            )
        )
        return {"queued": True, "event": "film/vlm.requested", "s3_key": s3_key}
    except Exception as e:
        logfire.warn("inngest vlm send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.post("/api/videos/script", tags=["pipeline"])
async def trigger_script(data: ScriptIn):
    logfire.info("enqueue script", film_id=str(data.film_id))
    try:
        await inngest_client.send(
            inngest.Event(
                name="film/script.requested",
                data={
                    "film_id": str(data.film_id),
                    "video_id": str(data.video_id) if data.video_id else "",
                },
            )
        )
        return {"queued": True, "event": "film/script.requested", "film_id": str(data.film_id)}
    except Exception as e:
        logfire.warn("inngest script send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.post("/api/videos/assemble", tags=["pipeline"])
async def trigger_assemble(data: AssembleIn):
    logfire.info("enqueue assemble", film_id=str(data.film_id))
    try:
        await inngest_client.send(
            inngest.Event(
                name="film/assemble.requested",
                data={
                    "film_id": str(data.film_id),
                    "video_id": str(data.video_id) if data.video_id else "",
                },
            )
        )
        return {"queued": True, "event": "film/assemble.requested", "film_id": str(data.film_id)}
    except Exception as e:
        logfire.warn("inngest assemble send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.post("/api/videos/safety", tags=["pipeline"])
async def trigger_safety(data: SafetyIn):
    logfire.info("enqueue safety", film_id=str(data.film_id))
    try:
        await inngest_client.send(
            inngest.Event(
                name="film/safety.requested",
                data={"film_id": str(data.film_id), "final_s3_key": data.final_s3_key or ""},
            )
        )
        return {"queued": True, "event": "film/safety.requested", "film_id": str(data.film_id)}
    except Exception as e:
        logfire.warn("inngest safety send failed", error=str(e))
        return JSONResponse(
            {"queued": False, "warning": "Inngest dev not reachable", "error": str(e)},
            status_code=202,
        )


@app.get("/api/proxy/{film_id}", tags=["pipeline"])
def get_proxy_status(film_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.models import Asset
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client

    proxy = db.query(Asset).filter(Asset.film_id == film_id, Asset.kind == "proxy_480p").first()  # type: ignore
    if not proxy:
        raise HTTPException(status_code=404, detail="proxy not found")
    try:
        s3 = get_s3_client()
        lst = s3.list_objects_v2(
            Bucket=str(proxy.runpod_volume_id or VOLUME_ID), Prefix=str(proxy.s3_key)
        )
        live = {"exists": lst.get("KeyCount", 0) > 0, "count": lst.get("KeyCount", 0)}
    except Exception as e:
        live = {"exists": None, "error": str(e)}
    return {
        "film_id": str(film_id),
        "s3_key": str(proxy.s3_key),
        "status": proxy.status,
        "size_bytes": proxy.size_bytes,
        "live": live,
    }


@app.get("/api/films/{film_id}/edit-decision", tags=["pipeline"])
def get_edit_decision(film_id: uuid.UUID):
    from app.assemble import build_edit_decision

    return build_edit_decision(str(film_id))


# Keep CLI entrypoint for `uv run main.py`
def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
