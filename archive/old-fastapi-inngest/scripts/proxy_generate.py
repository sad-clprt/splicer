"""01 — proxy_generate: 1080p → 480p_proxy via RunPod splicer-proxy (heavy, never local).

Payload: {"s3_key": source, "proxy_key": dest, "film_id": ...}
Uses scripts/runpod_client.run_sync on ENDPOINTS["proxy"] and polls until COMPLETED.
Verifies via S3 list and upserts assets/proxy_480p in scripts/application.db.

Do not run ffmpeg locally — this is the RunPod-only path. If endpoint is still
on generic runpod/base (throttled/IN_QUEUE forever), this will timeout with
actionable message to cloud-build serverless/proxy/Dockerfile via Hub.
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
SOURCE_KEY = f"films/{FILM_ID}/I.Am.Legend.1080p.mp4"
PROXY_KEY = f"films/{FILM_ID}/480p_proxy.mp4"


def run(film_id: str = FILM_ID, source_key: str = SOURCE_KEY, proxy_key: str = PROXY_KEY, conn=None, timeout: int = 1800) -> dict:
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
        from scripts.db import init_db as _init

        conn = _init()
        close_conn = True
    else:
        init_db(conn)

    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io")
    region = os.getenv("AWS_S3_REGION", "EU-RO-1")

    s3 = get_s3_client()
    # idempotency: if proxy already exists, skip heavy run
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=proxy_key)
        exists = any(o.get("Key") == proxy_key for o in lst.get("Contents", []) or [])
        size = next((o.get("Size") for o in lst.get("Contents", []) or [] if o.get("Key") == proxy_key), None)
        if exists:
            print(f"[01_proxy_generate] proxy already exists s3://{bucket}/{proxy_key} size={size} — skipping RunPod run (delete key to force)")
            upsert_asset(conn, film_id, "proxy_480p", proxy_key, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "proxy_key": proxy_key, "bucket": bucket, "size": size}
    except Exception as e:
        print(f"[01_proxy_generate] pre-check list failed: {e}")

    # verify source exists before queuing heavy job
    try:
        src_lst = s3.list_objects_v2(Bucket=bucket, Prefix=source_key)
        src_exists = any(o.get("Key") == source_key for o in src_lst.get("Contents", []) or [])
        if not src_exists:
            raise FileNotFoundError(f"source not found s3://{bucket}/{source_key}")
    except FileNotFoundError:
        raise
    except Exception as e:
        print(f"[01_proxy_generate] source check warning: {e}")

    job_id = insert_job(conn, film_id=film_id, kind="proxy", status="queued", runpod_job_id=None)
    print(f"[01_proxy_generate] film={film_id} source={source_key} proxy={proxy_key} bucket={bucket} endpoint={ENDPOINTS['proxy']}")

    payload = {"s3_key": source_key, "proxy_key": proxy_key, "film_id": film_id}
    endpoint = ENDPOINTS["proxy"]

    update_job(conn, job_id, status="running")

    try:
        status = run_sync(endpoint, payload, timeout=timeout, poll_interval=15, ensure_scaled=True)
        # status contains output from handler
        output = status.get("output") or status
        print(f"[01_proxy_generate] RunPod COMPLETED job={status.get('id')} output_keys={list(output.keys()) if isinstance(output, dict) else type(output)}")
        # verify S3
        lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=proxy_key)
        found = any(o.get("Key") == proxy_key for o in lst2.get("Contents", []) or [])
        size2 = next((o.get("Size") for o in lst2.get("Contents", []) or [] if o.get("Key") == proxy_key), None)
        if not found:
            raise RuntimeError(f"proxy not found after COMPLETED s3://{bucket}/{proxy_key} — handler may have written to different key, output={output}")
        print(f"[01_proxy_generate] verified s3://{bucket}/{proxy_key} size={size2}")
        upsert_asset(conn, film_id, "proxy_480p", proxy_key, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size2, status="available")
        update_job(conn, job_id, status="completed", runpod_job_id=str(status.get("id") or ""))
        if close_conn:
            conn.commit()
            conn.close()
        return {"proxy_key": proxy_key, "bucket": bucket, "size": size2, "output": output, "job_id": job_id}
    except TimeoutError as e:
        msg = (
            f"{e} — proxy endpoint likely still on generic runpod/base (handlers/bootstrap.py not executing). "
            "Fix: cloud-build serverless/proxy/Dockerfile via Hub (registry.runpod.net) to image with CMD python -u handler.py, update endpoint image."
        )
        print(f"[01_proxy_generate] TIMEOUT: {msg}")
        update_job(conn, job_id, status="failed", error=msg)
        if close_conn:
            conn.commit()
            conn.close()
        raise
    except Exception as e:
        print(f"[01_proxy_generate] FAILED: {e}")
        update_job(conn, job_id, status="failed", error=str(e)[:2000])
        if close_conn:
            conn.commit()
            conn.close()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="01 proxy generate via RunPod")
    parser.add_argument("--film-id", default=FILM_ID)
    parser.add_argument("--source-key", default=SOURCE_KEY)
    parser.add_argument("--proxy-key", default=PROXY_KEY)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    out = run(film_id=args.film_id, source_key=args.source_key, proxy_key=args.proxy_key, timeout=args.timeout)
    print(out)
