"""01 — proxy_download: fetch proxy from RunPod S3 to local for inspection.

Strictly download + verify (no transcode). Uses app.s3.download_s3_with_fallback
which handles RunPod HeadObject 403 via list_objects_v2 + streaming get_object.
Verifies with ffprobe (if available) that width=854 height=480.

Output to ./scripts/downloads/<film_id>/ or /tmp.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
PROXY_KEY = f"films/{FILM_ID}/480p_proxy.mp4"
DEST_DIR = Path(__file__).parent / "downloads"


def probe_video(path: Path) -> dict:
    """Lightweight ffprobe, never encodes."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name,avg_frame_rate,duration", "-of", "default=noprint_wrappers=1", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"probe": r.stdout.strip(), "stderr": r.stderr.strip(), "returncode": r.returncode}
    except FileNotFoundError:
        return {"probe": "", "error": "ffprobe not found — skip dimension check"}
    except Exception as e:
        return {"probe": "", "error": str(e)}


def run(film_id: str = FILM_ID, proxy_key: str = PROXY_KEY, dest: str | Path | None = None, conn=None) -> dict:
    import os

    from app.s3 import VOLUME_ID
    from app.s3 import download_s3_with_fallback
    from app.s3 import get_s3_client

    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3 = get_s3_client()

    # check S3 exists before download
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=proxy_key)
        found = any(o.get("Key") == proxy_key for o in lst.get("Contents", []) or [])
        size = next((o.get("Size") for o in lst.get("Contents", []) or [] if o.get("Key") == proxy_key), None)
        print(f"[01_proxy_download] s3://{bucket}/{proxy_key} exists={found} size={size}")
        if not found:
            raise FileNotFoundError(f"proxy not found s3://{bucket}/{proxy_key} — run scripts/proxy_generate.py first")
    except FileNotFoundError:
        raise
    except Exception as e:
        print(f"[01_proxy_download] list warning: {e}")

    if dest is None:
        dest = DEST_DIR / film_id / Path(proxy_key).name
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"[01_proxy_download] downloading s3://{bucket}/{proxy_key} -> {dest}")
    download_s3_with_fallback(s3, bucket, proxy_key, dest)
    actual = dest.stat().st_size if dest.exists() else 0
    print(f"[01_proxy_download] downloaded {actual} bytes to {dest}")

    info = probe_video(dest)
    print(f"[01_proxy_download] ffprobe: {info}")

    # basic dimension check — warn, don't fail
    if "854" in info.get("probe", "") and "480" in info.get("probe", ""):
        print("[01_proxy_download] verified 854x480")
    elif info.get("probe"):
        print(f"[01_proxy_download] WARNING proxy not 854x480: {info['probe']}")
    else:
        print("[01_proxy_download] no probe available — check manually")

    return {"proxy_key": proxy_key, "bucket": bucket, "dest": str(dest), "size": actual, "probe": info}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="01 proxy download")
    parser.add_argument("--film-id", default=FILM_ID)
    parser.add_argument("--proxy-key", default=PROXY_KEY)
    parser.add_argument("--dest", default=None)
    args = parser.parse_args()
    out = run(film_id=args.film_id, proxy_key=args.proxy_key, dest=args.dest)
    print(out)
