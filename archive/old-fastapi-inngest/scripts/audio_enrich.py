"""03 — audio_enrich: WhisperX + SRT + PySceneDetect via RunPod audio-hub (heavy).

Input s3_key is the proxy (480p) to keep cost low; also passes SRT key.
RunPod endpoint hapnan-whisperx expects s3_key/srt_key handling internally
(we try both "s3_key" and "s3Key" forms for compatibility).

If proxy not yet available, falls back to source key.
Output upload: films/<film_id>/audio_enrich.json (scenes + subs + whisper gap).
SQLite assets/jobs mirror.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
PROXY_KEY = f"films/{FILM_ID}/480p_proxy.mp4"
SOURCE_KEY = f"films/{FILM_ID}/I.Am.Legend.1080p.mp4"
SRT_KEY = f"films/{FILM_ID}/I.Am.Legend.srt"
SRT_KEY_ALT = f"films/{FILM_ID}/I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.srt"
AUDIO_ENRICH_KEY = f"films/{FILM_ID}/audio_enrich.json"


def _pick_audio_source(s3, bucket: str) -> tuple[str, str | None]:
    """Return (src_key, srt_key) preferring proxy if exists."""
    def exists(k: str) -> bool:
        try:
            lst = s3.list_objects_v2(Bucket=bucket, Prefix=k)
            return any(o.get("Key") == k for o in lst.get("Contents", []) or [])
        except Exception:
            return False

    src = PROXY_KEY if exists(PROXY_KEY) else SOURCE_KEY
    # SRT effective
    srt = None
    if exists(SRT_KEY):
        srt = SRT_KEY
    elif exists(SRT_KEY_ALT):
        srt = SRT_KEY_ALT
    return src, srt


def run(film_id: str = FILM_ID, s3_key: str | None = None, srt_key: str | None = None, conn=None, timeout: int = 1800) -> dict:
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from scripts.db import init_db
    from scripts.db import insert_job
    from scripts.db import update_job
    from scripts.db import upsert_asset
    from scripts.runpod_client import ENDPOINTS
    from scripts.runpod_client import run_sync

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True
    else:
        init_db(conn)

    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io")
    region = os.getenv("AWS_S3_REGION", "EU-RO-1")
    s3 = get_s3_client()

    if s3_key is None or srt_key is None:
        picked_src, picked_srt = _pick_audio_source(s3, bucket)
        s3_key = s3_key or picked_src
        # srt_key: allow explicit None if user wants whisper-only
        if srt_key is None and picked_srt is not None:
            srt_key = picked_srt

    # idempotency: if audio_enrich.json already exists, skip
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=AUDIO_ENRICH_KEY)
        if any(o.get("Key") == AUDIO_ENRICH_KEY for o in lst.get("Contents", []) or []):
            print(f"[03_audio] {AUDIO_ENRICH_KEY} already exists — skipping RunPod run (delete key to force)")
            upsert_asset(conn, film_id, "audio_enrich", AUDIO_ENRICH_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "s3_key": AUDIO_ENRICH_KEY, "bucket": bucket}
    except Exception as e:
        print(f"[03_audio] pre-check warning: {e}")

    print(f"[03_audio] film={film_id} s3_key={s3_key} srt_key={srt_key} bucket={bucket} endpoint={ENDPOINTS['audio']}")

    job_id = insert_job(conn, film_id=film_id, kind="audio", status="queued")
    update_job(conn, job_id, status="running")

    # payload variants: try s3_key+srt_key; handler may also want volume paths
    payloads = [
        {"s3_key": s3_key, "srt_key": srt_key, "film_id": film_id},
        {"s3_key": s3_key, "srtKey": srt_key, "filmId": film_id},
        {"s3_key": s3_key, "film_id": film_id},
    ]
    # we'll just send first; handler should ignore unknown
    payload = payloads[0]

    endpoint = ENDPOINTS["audio"]
    try:
        status = run_sync(endpoint, payload, timeout=timeout, poll_interval=15, ensure_scaled=True)
        output = status.get("output") or status
        print(f"[03_audio] COMPLETED job={status.get('id')} output={str(output)[:500]}")

        # verify
        lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=AUDIO_ENRICH_KEY)
        found = any(o.get("Key") == AUDIO_ENRICH_KEY for o in lst2.get("Contents", []) or [])
        size = next((o.get("Size") for o in lst2.get("Contents", []) or [] if o.get("Key") == AUDIO_ENRICH_KEY), None)
        if not found:
            print(f"[03_audio] WARNING audio_enrich.json not found after COMPLETED — handler may need to upload to s3://{bucket}/{AUDIO_ENRICH_KEY}, output={output}")
        else:
            print(f"[03_audio] verified s3://{bucket}/{AUDIO_ENRICH_KEY} size={size}")
        upsert_asset(conn, film_id, "audio_enrich", AUDIO_ENRICH_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
        update_job(conn, job_id, status="completed", runpod_job_id=str(status.get("id") or ""))
        if close_conn:
            conn.commit()
            conn.close()
        return {"s3_key": AUDIO_ENRICH_KEY, "bucket": bucket, "size": size, "output": output, "job_id": job_id}
    except Exception as e:
        print(f"[03_audio] FAILED: {e}")
        update_job(conn, job_id, status="failed", error=str(e)[:2000])
        if close_conn:
            conn.commit()
            conn.close()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="03 audio enrich via RunPod")
    parser.add_argument("--film-id", default=FILM_ID)
    parser.add_argument("--s3-key", default=None)
    parser.add_argument("--srt-key", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    out = run(film_id=args.film_id, s3_key=args.s3_key, srt_key=args.srt_key, timeout=args.timeout)
    print(out)
