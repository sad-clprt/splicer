"""04 — vlm_generate: hierarchical Qwen3-VL-8B-Instruct via RunPod vlm-hub (heavy, 1 FPS).

Uses proxy_480p locally extracted frames on RunPod worker (NVDEC), 8-frame batches,
stages: stage1 clips (675 from 5400 frames @1FPS) → stage2 fuse (audio scenes + KB) → stage3 beats.
We delegate full hierarchy to RunPod; handler uploads:
  films/<film_id>/vlm/stage1.json, stage2.json, stage3.json, vlm.json

Polls RunPod and mirrors to SQLite.
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
AUDIO_ENRICH_KEY = f"films/{FILM_ID}/audio_enrich.json"
VLM_PREFIX = f"films/{FILM_ID}/vlm/"
STAGE1_KEY = f"films/{FILM_ID}/vlm/stage1.json"
STAGE3_KEY = f"films/{FILM_ID}/vlm/stage3.json"


def run(film_id: str = FILM_ID, s3_key: str | None = None, audio_enrich_key: str | None = AUDIO_ENRICH_KEY, conn=None, timeout: int = 2400) -> dict:
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

    # pick proxy if exists else source
    if s3_key is None:
        try:
            lst = s3.list_objects_v2(Bucket=bucket, Prefix=PROXY_KEY)
            s3_key = PROXY_KEY if any(o.get("Key") == PROXY_KEY for o in lst.get("Contents", []) or []) else f"films/{film_id}/I.Am.Legend.1080p.mp4"
        except Exception:
            s3_key = PROXY_KEY

    # idempotency: if stage3 already exists, skip
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=STAGE3_KEY)
        if any(o.get("Key") == STAGE3_KEY for o in lst.get("Contents", []) or []):
            print(f"[04_vlm] {STAGE3_KEY} already exists — skipping (delete to force)")
            upsert_asset(conn, film_id, "vlm", STAGE3_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "s3_key": STAGE3_KEY}
    except Exception as e:
        print(f"[04_vlm] pre-check warning: {e}")

    print(f"[04_vlm] film={film_id} s3_key={s3_key} audio_enrich={audio_enrich_key} endpoint={ENDPOINTS['vlm']}")

    job_id = insert_job(conn, film_id=film_id, kind="vlm", status="queued")
    update_job(conn, job_id, status="running")

    # payload: VLM worker is vLLM OpenAI-compatible; guidance is to send OpenAI messages format.
    # Our worker wrapper (if any) may expect s3_key + prompt. We send both shapes.
    payload = {
        "s3_key": s3_key,
        "film_id": film_id,
        "audio_enrich_key": audio_enrich_key,
        # OpenAI-style hint for worker-vllm direct passthrough
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "messages": [
            {"role": "system", "content": "You are a video scene analyzer. Return JSON with chars, actions, importance."},
            {"role": "user", "content": f"Analyze film s3://{bucket}/{s3_key} at 1 FPS, 8-frame batches; fuse with audio_enrich.json; output stage3 beats."},
        ],
        "max_tokens": 256,
    }

    endpoint = ENDPOINTS["vlm"]
    try:
        status = run_sync(endpoint, payload, timeout=timeout, poll_interval=15, ensure_scaled=True)
        output = status.get("output") or status
        print(f"[04_vlm] COMPLETED job={status.get('id')} output_preview={str(output)[:600]}")

        # verify expected keys
        for key, kind in [(STAGE1_KEY, "vlm"), (STAGE3_KEY, "vlm"), (f"films/{film_id}/vlm/vlm.json", "vlm")]:
            try:
                lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=key)
                found = any(o.get("Key") == key for o in lst2.get("Contents", []) or [])
                size = next((o.get("Size") for o in lst2.get("Contents", []) or [] if o.get("Key") == key), None)
                print(f"  check {key} found={found} size={size}")
                if found:
                    upsert_asset(conn, film_id, kind, key, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
            except Exception as e:
                print(f"  verify {key} error: {e}")

        update_job(conn, job_id, status="completed", runpod_job_id=str(status.get("id") or ""))
        if close_conn:
            conn.commit()
            conn.close()
        return {"film_id": film_id, "s3_key": s3_key, "output": output, "job_id": job_id}
    except Exception as e:
        print(f"[04_vlm] FAILED: {e}")
        update_job(conn, job_id, status="failed", error=str(e)[:2000])
        if close_conn:
            conn.commit()
            conn.close()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="04 vlm hierarchical via RunPod")
    parser.add_argument("--film-id", default=FILM_ID)
    parser.add_argument("--s3-key", default=None)
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()
    out = run(film_id=args.film_id, s3_key=args.s3_key, timeout=args.timeout)
    print(out)
