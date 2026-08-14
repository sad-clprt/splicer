"""00 — check source: verify canary film + S3 source + SRT exist, seed SQLite.

Lightweight: S3 list only, no heavy work. RunPod S3 403 fallback via app.s3.

Creates films/assets rows in scripts/application.db (no ORM, sqlite3).
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
TITLE = "I Am Legend"
YEAR = 2007
SOURCE_KEY = f"films/{FILM_ID}/I.Am.Legend.1080p.mp4"
SRT_KEY = f"films/{FILM_ID}/I.Am.Legend.srt"
# alternate SRT key that upload_srt.py used
SRT_KEY_ALT = f"films/{FILM_ID}/I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.srt"


def run(film_id: str = FILM_ID, conn=None) -> dict:
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from scripts.db import ensure_film
    from scripts.db import init_db
    from scripts.db import upsert_asset

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True
    else:
        init_db(conn)

    ensure_film(conn, film_id, title=TITLE, year=YEAR)

    s3 = get_s3_client()
    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io")
    region = os.getenv("AWS_S3_REGION", "EU-RO-1")

    def check_key(key: str) -> dict:
        try:
            lst = s3.list_objects_v2(Bucket=bucket, Prefix=key)
            found = any(o.get("Key") == key for o in lst.get("Contents", []) or [])
            size = next((o["Size"] for o in lst.get("Contents", []) or [] if o.get("Key") == key), None)
            return {"exists": found, "size": size, "count": lst.get("KeyCount", 0), "key": key}
        except Exception as e:
            return {"exists": False, "error": str(e), "key": key}

    src = check_key(SOURCE_KEY)
    srt = check_key(SRT_KEY)
    srt_alt = check_key(SRT_KEY_ALT)
    # pick whichever SRT exists
    srt_effective = SRT_KEY if srt.get("exists") else (SRT_KEY_ALT if srt_alt.get("exists") else SRT_KEY)

    print(f"[00_check] bucket={bucket} film={film_id}")
    print(f"  source {SOURCE_KEY} exists={src.get('exists')} size={src.get('size')} {src.get('error','')}")
    print(f"  srt    {SRT_KEY} exists={srt.get('exists')} size={srt.get('size')}")
    print(f"  srtAlt {SRT_KEY_ALT} exists={srt_alt.get('exists')} size={srt_alt.get('size')}")
    print(f"  effective srt: {srt_effective}")

    if not src.get("exists"):
        msg = f"source not found: {SOURCE_KEY} — upload 1.5G mp4 to s3://{bucket}/{SOURCE_KEY} first"
        if close_conn:
            conn.close()
        raise FileNotFoundError(msg)

    # upsert assets (idempotent)
    src_size = src.get("size")
    # find effective srt size for asset
    srt_size = srt.get("size") if srt.get("exists") else srt_alt.get("size")
    upsert_asset(conn, film_id, "source_1080p", SOURCE_KEY, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=src_size, status="available")
    if srt.get("exists") or srt_alt.get("exists"):
        upsert_asset(conn, film_id, "subtitle", srt_effective, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=srt_size, status="available")
    else:
        print("[00_check] WARNING srt not found — audio stage will run without subtitles (WhisperX only)")

    # summary
    from scripts.db import get_assets_for_film

    assets = get_assets_for_film(conn, film_id)
    print(f"[00_check] done assets={len(assets)} for film={film_id}")
    for a in assets:
        print(f"  asset {a['kind']} {a['s3_key']} size={a['size_bytes']} status={a['status']}")

    if close_conn:
        conn.commit()
        conn.close()

    return {
        "film_id": film_id,
        "bucket": bucket,
        "source": src,
        "srt": srt,
        "srt_alt": srt_alt,
        "effective_srt": srt_effective,
        "assets": len(assets),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="00 check source")
    parser.add_argument("--film-id", default=FILM_ID)
    args = parser.parse_args()
    out = run(film_id=args.film_id)
    print(out)
