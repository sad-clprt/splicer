"""06b — assemble: build edit_decision.json + Blender/NVENC final 1080p via RunPod (heavy).

Calls app.assemble.build_edit_decision locally (uses audio_enrich + safety_flags + script)
to create edit_decision.json, uploads it, then delegates final render to RunPod.
If assemble endpoint not separately provisioned, reuses proxy endpoint (ffmpeg+blender base)
with payload {edit_decision_key, film_id}.

For now, if blender not on worker, returns stub result and leaves final_1080p.mp4
pending — pipeline can continue to safety after TTS.

Heavy render is never local.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
EDIT_DECISION_KEY = f"films/{FILM_ID}/edit_decision.json"
FINAL_KEY = f"films/{FILM_ID}/final_1080p.mp4"
TTS_KEY = f"films/{FILM_ID}/tts.wav"


def run(film_id: str = FILM_ID, video_id: str | None = None, conn=None, timeout: int = 2400) -> dict:
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from scripts.db import init_db
    from scripts.db import insert_job
    from scripts.db import update_job
    from scripts.db import upsert_asset

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

    # Build edit_decision via app.assemble (needs audio_enrich.json + script etc from S3/DB)
    # app.assemble.build_edit_decision handles missing keys gracefully.
    try:
        from app.assemble import build_edit_decision

        edl = build_edit_decision(film_id, fps=24)
    except Exception as e:
        print(f"[06_assemble] build_edit_decision failed: {e} — using minimal stub")
        edl = {
            "film_id": film_id,
            "fps": 24,
            "proxy_s3_key": f"films/{film_id}/480p_proxy.mp4",
            "original_s3_key": f"films/{film_id}/I.Am.Legend.1080p.mp4",
            "edit_version": "v1",
            "scenes": [],
            "markers": [],
            "safety_flags": [],
            "script": {"text": "", "segments": []},
            "export": {"width": 1920, "height": 1080, "fps": 24, "gop": 30, "video_codec": "h264_nvenc", "preset": "slow", "rc": "vbr_hq", "cq": 23, "bitrate_kbps": 8000},
        }

    # upload EDL
    with tempfile.TemporaryDirectory() as tmpdir:
        edl_path = Path(tmpdir) / "edit_decision.json"
        edl_path.write_text(json.dumps(edl, indent=2))
        s3.upload_file(str(edl_path), bucket, EDIT_DECISION_KEY)
        scenes_val = edl.get("scenes")
        markers_val = edl.get("markers")
        scenes_len = len(scenes_val) if isinstance(scenes_val, list) else 0
        markers_len = len(markers_val) if isinstance(markers_val, list) else 0
        print(f"[06_assemble] uploaded edit_decision s3://{bucket}/{EDIT_DECISION_KEY} scenes={scenes_len} markers={markers_len}")
        upsert_asset(conn, film_id, "edit_decision", EDIT_DECISION_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, status="available")

    # idempotency: if final already exists, skip heavy render
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=FINAL_KEY)
        if any(o.get("Key") == FINAL_KEY for o in lst.get("Contents", []) or []):
            size = next((o["Size"] for o in lst.get("Contents", []) or [] if o.get("Key") == FINAL_KEY), None)
            print(f"[06_assemble] final already exists s3://{bucket}/{FINAL_KEY} size={size} — skipping render")
            upsert_asset(conn, film_id, "final_1080p", FINAL_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "final_key": FINAL_KEY, "edl_key": EDIT_DECISION_KEY}
    except Exception as e:
        print(f"[06_assemble] final check warning: {e}")

    # heavy render via RunPod — try dedicated assemble endpoint if env set, else reuse proxy
    assemble_endpoint = os.getenv("RUNPOD_ASSEMBLE_ENDPOINT") or os.getenv("ASSEMBLE_ENDPOINT")
    if not assemble_endpoint:
        # reuse proxy endpoint id for now (ffmpeg+NVENC base has blender potential)
        from scripts.runpod_client import ENDPOINTS

        assemble_endpoint = ENDPOINTS["proxy"]
        print(f"[06_assemble] no dedicated assemble endpoint env, reusing proxy {assemble_endpoint}")

    job_id = insert_job(conn, film_id=film_id, kind="assemble", status="queued", video_id=video_id)
    update_job(conn, job_id, status="running")

    payload = {"film_id": film_id, "edit_decision_key": EDIT_DECISION_KEY, "tts_key": TTS_KEY, "final_key": FINAL_KEY}

    try:
        from scripts.runpod_client import run_sync

        # assemble render can take 10-20m for 14m output at NVENC
        status = run_sync(assemble_endpoint, payload, timeout=timeout, poll_interval=20, ensure_scaled=True)
        output = status.get("output") or status
        print(f"[06_assemble] COMPLETED output={str(output)[:800]}")
        # verify final
        try:
            lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=FINAL_KEY)
            found = any(o.get("Key") == FINAL_KEY for o in lst2.get("Contents", []) or [])
            size2 = next((o["Size"] for o in lst2.get("Contents", []) or [] if o.get("Key") == FINAL_KEY), None)
            if found:
                print(f"[06_assemble] verified final s3://{bucket}/{FINAL_KEY} size={size2}")
                upsert_asset(conn, film_id, "final_1080p", FINAL_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size2, status="available")
            else:
                print(f"[06_assemble] final not found after COMPLETED — worker may need blender image, output={output}")
                # keep as pending, not failure — safety can run on proxy/tts
        except Exception as e:
            print(f"[06_assemble] verify error: {e}")
        update_job(conn, job_id, status="completed", runpod_job_id=str(status.get("id") or ""))
        if close_conn:
            conn.commit()
            conn.close()
        return {"final_key": FINAL_KEY, "edl_key": EDIT_DECISION_KEY, "output": output, "job_id": job_id}
    except Exception as e:
        print(f"[06_assemble] FAILED (final render not yet on RunPod): {e}")
        # don't fail whole pipeline for missing blender — mark as pending
        update_job(conn, job_id, status="failed", error=str(e)[:2000])
        if close_conn:
            conn.commit()
            conn.close()
        # return edl success even if final pending — allows safety to run on proxy
        return {"final_key": FINAL_KEY, "edl_key": EDIT_DECISION_KEY, "error": str(e), "pending": True}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="06b assemble via RunPod")
    parser.add_argument("--film-id", default=FILM_ID)
    args = parser.parse_args()
    out = run(film_id=args.film_id)
    print(out)
