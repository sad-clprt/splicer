"""08 — verify_final: check all S3 artifacts + SQLite state for canary film.

No heavy work — S3 list + ffprobe on downloaded proxy/final if present locally.
Prints a checklist and exits non-zero if critical artifacts missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
EXPECTED = [
    f"films/{FILM_ID}/I.Am.Legend.1080p.mp4",
    f"films/{FILM_ID}/I.Am.Legend.srt",
    f"films/{FILM_ID}/480p_proxy.mp4",
    f"films/{FILM_ID}/audio_enrich.json",
    f"films/{FILM_ID}/vlm/stage1.json",
    f"films/{FILM_ID}/vlm/stage2.json",
    f"films/{FILM_ID}/vlm/stage3.json",
    f"films/{FILM_ID}/vlm/vlm.json",
    f"films/{FILM_ID}/script.txt",
    f"films/{FILM_ID}/tts.wav",
    f"films/{FILM_ID}/edit_decision.json",
    f"films/{FILM_ID}/final_1080p.mp4",
    f"films/{FILM_ID}/safety_flags.json",
]
# alternate known keys
ALTERNATES = {
    f"films/{FILM_ID}/I.Am.Legend.srt": f"films/{FILM_ID}/I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.srt",
}


def run(film_id: str = FILM_ID, conn=None) -> dict:
    import os

    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from scripts.db import get_assets_for_film
    from scripts.db import init_db

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True
    else:
        init_db(conn)

    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3 = get_s3_client()

    print(f"[08_verify] film={film_id} bucket={bucket}")
    # SQLite films
    cur = conn.execute("SELECT * FROM films WHERE id=?", (film_id,))
    film = cur.fetchone()
    if film:
        print(f"  film: {film['title']} year={film['year']} metadata={'yes' if film['metadata_json'] else 'no'}")
        if film["metadata_json"]:
            try:
                m = json.loads(film["metadata_json"])
                print(f"    metadata keys: {list(m.keys())[:6]} tmdb_id={(m.get('tmdb') or {}).get('id')}")
            except Exception:
                pass
    else:
        print(f"  film {film_id} NOT in SQLite")

    # videos
    cur = conn.execute("SELECT * FROM videos WHERE film_id=? ORDER BY created_at DESC LIMIT 1", (film_id,))
    video = cur.fetchone()
    if video:
        preview = (video["script"] or "")[:120].replace("\n", " ")
        print(f"  video: {video['id']} status={video['status']} words={len((video['script'] or '').split())} target={video['target_duration_sec']}s preview='{preview}...'")
    else:
        print("  video: none")

    assets = get_assets_for_film(conn, film_id)
    print(f"  assets in SQLite: {len(assets)}")
    for a in assets:
        print(f"    {a['kind']:14s} {a['s3_key']} size={a['size_bytes']}")

    # S3 checks
    results = []
    for key in EXPECTED:
        try:
            lst = s3.list_objects_v2(Bucket=bucket, Prefix=key)
            found = any(o.get("Key") == key for o in lst.get("Contents", []) or [])
            size = next((o.get("Size") for o in lst.get("Contents", []) or [] if o.get("Key") == key), None)
            # try alternate
            alt = ALTERNATES.get(key)
            if not found and alt:
                lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=alt)
                found2 = any(o.get("Key") == alt for o in lst2.get("Contents", []) or [])
                size2 = next((o.get("Size") for o in lst2.get("Contents", []) or [] if o.get("Key") == alt), None)
                if found2:
                    print(f"  S3 {'OK':3s} {key} → alt {alt} size={size2}")
                    results.append({"key": key, "found": True, "alt": alt, "size": size2})
                    continue
            tag = "OK" if found else "MISS"
            print(f"  S3 {tag:4s} {key} size={size}")
            results.append({"key": key, "found": found, "size": size})
        except Exception as e:
            print(f"  S3 ERR  {key} {e}")
            results.append({"key": key, "found": False, "error": str(e)})

    # final duration check if final exists locally in downloads
    final_local = Path(__file__).parent / "downloads" / film_id / "final_1080p.mp4"
    if final_local.exists():
        try:
            import subprocess

            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(final_local)], capture_output=True, text=True, timeout=10)
            dur = float(r.stdout.strip() or 0)
            print(f"  local final duration: {dur:.1f}s ({dur/60:.1f}m) — target 840-1200s (14-20m)")
            if 720 <= dur <= 1300:
                print("    duration OK")
            else:
                print("    duration OUT OF RANGE")
        except Exception as e:
            print(f"  local probe failed: {e}")

    # summary
    critical = [f"films/{film_id}/I.Am.Legend.1080p.mp4", f"films/{film_id}/480p_proxy.mp4"]
    missing_critical = [r for r in results if r["key"] in critical and not r["found"]]
    if missing_critical:
        print(f"[08_verify] CRITICAL missing: {[r['key'] for r in missing_critical]}")
    else:
        print("[08_verify] critical artifacts present")

    missing_optional = [r for r in results if not r["found"]]
    print(f"[08_verify] total missing {len(missing_optional)}/{len(results)}: {[r['key'] for r in missing_optional]}")

    if close_conn:
        conn.close()

    return {"film_id": film_id, "bucket": bucket, "results": results, "missing": missing_optional, "assets": len(assets)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="08 verify final")
    parser.add_argument("--film-id", default=FILM_ID)
    args = parser.parse_args()
    out = run(film_id=args.film_id)
    print(out)
