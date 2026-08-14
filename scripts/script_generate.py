"""05 — script_generate: beats + KB + audio → 14-20m voiceover via OpenRouter (lightweight, local HTTP).

Not heavy: calls OpenRouter API (qwen/qwen3-32b, max_tokens 6000) locally.
If OPENROUTER_API_KEY missing, writes stub script.
Uploads films/<film_id>/script.txt to S3 and mirrors to SQLite videos table.
"""

from __future__ import annotations

import hashlib
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
SCRIPT_KEY = f"films/{FILM_ID}/script.txt"
STAGE3_KEY = f"films/{FILM_ID}/vlm/stage3.json"
AUDIO_ENRICH_KEY = f"films/{FILM_ID}/audio_enrich.json"


def _load_json_from_s3(s3, bucket: str, key: str):
    from app.s3 import download_s3_with_fallback

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tmp.close()
    try:
        download_s3_with_fallback(s3, bucket, key, tmp.name)
        return json.loads(Path(tmp.name).read_text(encoding="utf-8", errors="ignore"))
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[05_script] load {key} error: {e}")
        return None
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass


def run(film_id: str = FILM_ID, video_id: str | None = None, conn=None) -> dict:
    import uuid

    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client
    from scripts.db import init_db

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

    # fetch beats + audio scenes
    beats_data = _load_json_from_s3(s3, bucket, STAGE3_KEY) or _load_json_from_s3(s3, bucket, STAGE3_KEY.replace("stage3.json", "vlm.json"))
    beats = []
    if isinstance(beats_data, dict):
        beats = beats_data.get("beats") or beats_data.get("stage3", {}).get("beats") or []
    elif isinstance(beats_data, list):
        beats = beats_data

    audio_data = _load_json_from_s3(s3, bucket, AUDIO_ENRICH_KEY)
    audio_scenes = []
    if isinstance(audio_data, dict):
        audio_scenes = audio_data.get("scenes", [])

    # fetch film metadata from SQLite
    cur = conn.execute("SELECT * FROM films WHERE id=?", (film_id,))
    film = cur.fetchone()
    metadata = None
    if film and film["metadata_json"]:
        try:
            metadata = json.loads(film["metadata_json"])
        except Exception:
            metadata = None

    # if no metadata yet, try to ensure film row
    if not film:
        from datetime import UTC
        from datetime import datetime

        conn.execute(
            "INSERT OR IGNORE INTO films (id, title, year, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (film_id, "I Am Legend", 2007, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        metadata = None

    print(f"[05_script] film={film_id} beats={len(beats)} audio_scenes={len(audio_scenes)} has_metadata={bool(metadata)}")

    # build prompt + call OpenRouter (via app.script helper to reuse logic)
    try:
        from app.script import _openrouter_chat
        from app.script import build_prompt

        prompt = build_prompt(beats, metadata, audio_scenes)
        script = _openrouter_chat(prompt)
    except Exception as e:
        print(f"[05_script] app.script failed: {e} — using stub")
        script = f"[STUB SCRIPT for {film_id}] In a desolate New York, Robert Neville ... beats preview {json.dumps(beats[:2])[:500]} (set OPENROUTER_API_KEY for real)"

    words = len(script.split())
    h = hashlib.sha256(script.encode()).hexdigest()[:16]
    est_sec = int(words / 150 * 60)
    est_sec = max(720, min(1200, est_sec))

    # upsert video row in SQLite
    vid = video_id
    if not vid:
        cur = conn.execute("SELECT id FROM videos WHERE film_id=? ORDER BY created_at DESC LIMIT 1", (film_id,))
        row = cur.fetchone()
        vid = row["id"] if row else None
    if not vid:
        vid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO videos (id, film_id, status, script, script_hash, target_duration_sec, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (vid, film_id, "scripting", script, h, est_sec),
        )
    else:
        conn.execute(
            "UPDATE videos SET script=?, script_hash=?, target_duration_sec=?, status=?, updated_at=datetime('now') WHERE id=?",
            (script, h, est_sec, "scripting", vid),
        )

    # upload script.txt to S3
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tf:
        tf.write(script)
        tf.flush()
        s3.upload_file(tf.name, bucket, SCRIPT_KEY)
        Path(tf.name).unlink(missing_ok=True)

    # also mirror asset
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=SCRIPT_KEY)
        size = next((o["Size"] for o in lst.get("Contents", []) or [] if o.get("Key") == SCRIPT_KEY), None)
    except Exception:
        size = None

    conn.execute(
        "INSERT OR REPLACE INTO assets (id, film_id, kind, s3_key, bucket, s3_endpoint, datacenter, size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (str(uuid.uuid4()), film_id, "script", SCRIPT_KEY, bucket, s3_endpoint, region, size, "available"),
    )

    print(f"[05_script] video={vid} words={words} est_sec={est_sec} hash={h} uploaded s3://{bucket}/{SCRIPT_KEY}")

    if close_conn:
        conn.commit()
        conn.close()

    return {"video_id": vid, "film_id": film_id, "script_hash": h, "words": words, "target_duration_sec": est_sec, "s3_key": SCRIPT_KEY, "script_preview": script[:500]}
