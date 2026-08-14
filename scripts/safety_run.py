"""07 — safety_run: Shieldstral on final video via RunPod safety-hub (heavy, final only).

Runs on 14-20m final @1 FPS → 840-1200 frames (not source 90m → 5400 frames).
Payload: {film_id, final_s3_key} → uploads films/<film_id>/safety_flags.json.

If final not yet rendered, falls back to proxy with note.
Strict: no local safety inference — only RunPod vLLM Shieldstral.
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
FINAL_KEY = f"films/{FILM_ID}/final_1080p.mp4"
PROXY_KEY = f"films/{FILM_ID}/480p_proxy.mp4"
SAFETY_KEY = f"films/{FILM_ID}/safety_flags.json"


def run(film_id: str = FILM_ID, final_s3_key: str | None = None, conn=None, timeout: int = 1800) -> dict:
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

    # pick final if exists, else proxy (with warning)
    target = final_s3_key or FINAL_KEY
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=target)
        if not any(o.get("Key") == target for o in lst.get("Contents", []) or []):
            print(f"[07_safety] {target} not found — falling back to proxy for preview")
            target = PROXY_KEY
            lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=target)
            if not any(o.get("Key") == target for o in lst2.get("Contents", []) or []):
                raise FileNotFoundError(f"neither final nor proxy found for safety: {FINAL_KEY}")
    except FileNotFoundError:
        raise
    except Exception as e:
        print(f"[07_safety] target check warning: {e}")

    # idempotency
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=SAFETY_KEY)
        if any(o.get("Key") == SAFETY_KEY for o in lst.get("Contents", []) or []):
            print(f"[07_safety] {SAFETY_KEY} already exists — skipping (delete to force re-scan)")
            upsert_asset(conn, film_id, "safety", SAFETY_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "safety_key": SAFETY_KEY}
    except Exception as e:
        print(f"[07_safety] pre-check warning: {e}")

    print(f"[07_safety] film={film_id} target={target} safety_key={SAFETY_KEY} endpoint={ENDPOINTS['safety']}")

    job_id = insert_job(conn, film_id=film_id, kind="safety", status="queued")
    update_job(conn, job_id, status="running")

    endpoint = ENDPOINTS["safety"]
    payload = {
        "s3_key": target,
        "final_s3_key": target,
        "film_id": film_id,
        "model": "mistralai/Shieldstral-1.0-3B",
        "threshold": 0.5,
        "fps": 1,
    }

    try:
        status = run_sync(endpoint, payload, timeout=timeout, poll_interval=15, ensure_scaled=True)
        output = status.get("output") or status
        print(f"[07_safety] COMPLETED job={status.get('id')} output={str(output)[:600]}")

        # verify safety_flags.json exists (worker should upload)
        try:
            lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=SAFETY_KEY)
            found = any(o.get("Key") == SAFETY_KEY for o in lst2.get("Contents", []) or [])
            size = next((o.get("Size") for o in lst2.get("Contents", []) or [] if o.get("Key") == SAFETY_KEY), None)
            if found:
                print(f"[07_safety] verified s3://{bucket}/{SAFETY_KEY} size={size}")
                upsert_asset(conn, film_id, "safety", SAFETY_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
            else:
                print(f"[07_safety] safety_flags.json not found after COMPLETED — output may contain flags inline: {output}")
                # try to upload output inline if it looks like flags
                if isinstance(output, dict) and "flags" in output:
                    import json
                    import tempfile

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as tf:
                        json.dump(output.get("flags"), tf)
                        tf.flush()
                        s3.upload_file(tf.name, bucket, SAFETY_KEY)
                        Path(tf.name).unlink(missing_ok=True)
                        print(f"[07_safety] uploaded flags from output to s3://{bucket}/{SAFETY_KEY}")
        except Exception as e:
            print(f"[07_safety] verify warning: {e}")

        update_job(conn, job_id, status="completed", runpod_job_id=str(status.get("id") or ""))
        if close_conn:
            conn.commit()
            conn.close()
        return {"safety_key": SAFETY_KEY, "bucket": bucket, "target": target, "output": output, "job_id": job_id}
    except Exception as e:
        print(f"[07_safety] FAILED: {e}")
        update_job(conn, job_id, status="failed", error=str(e)[:2000])
        if close_conn:
            conn.commit()
            conn.close()
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="07 safety via RunPod")
    parser.add_argument("--film-id", default=FILM_ID)
    args = parser.parse_args()
    out = run(film_id=args.film_id)
    print(out)
