import logging
import os

import inngest
import inngest.fast_api
import logfire
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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

# --- FastAPI ---
app = FastAPI(
    title="Splicer",
    description="Movie recap pipeline API — concurrent proxy, scenes, safety, script, TTS, assemble",
    version="0.1.0",
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
    concurrency=[inngest.Concurrency(limit=5)],  # 5 concurrent films as you requested
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


# Example parallel proxy trigger (skeleton for your 5 simultaneous proxies)
@inngest_client.create_function(
    fn_id="proxy-film",
    trigger=inngest.TriggerEvent(event="film/proxy.requested"),
    concurrency=[inngest.Concurrency(limit=5)],
    retries=3,
)
async def proxy_film(ctx: inngest.Context) -> dict:
    film_id = str(ctx.event.data.get("film_id", "unknown"))
    s3_key = str(ctx.event.data.get("s3_key", ""))
    with logfire.span("proxy_film", film_id=film_id):
        logfire.info("proxy requested", film_id=film_id, s3_key=s3_key)

        async def _touch():
            return {"s3_key": s3_key, "proxy_key": s3_key.replace("1080p", "480p_proxy")}

        steps = await ctx.step.run("touch-runpod-s3", _touch)
        return steps


inngest.fast_api.serve(app, inngest_client, [hello_pipeline, proxy_film])


# --- Pydantic schemas ---
class HelloIn(BaseModel):
    film_title: str = "I Am Legend"


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


# --- Routes ---
@app.get("/", response_model=HealthOut, tags=["system"])
def root():
    logfire.info("root hit")
    return HealthOut(status="ok", service="splicer", version="0.1.0")


@app.get("/health", response_model=HealthOut, tags=["system"])
def health():
    return HealthOut(status="ok", service="splicer", version="0.1.0")


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
            {"queued": False, "warning": "Inngest dev server not reachable — start `inngest dev -u http://localhost:8000/api/inngest`", "error": str(e), "data": data.model_dump()},
            status_code=202,
        )


@app.get("/api/inngest/health", tags=["system"])
def inngest_health():
    return {"inngest_app_id": inngest_client.app_id, "is_production": inngest_client.is_production}


# Keep CLI entrypoint for `uv run main.py`
def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
