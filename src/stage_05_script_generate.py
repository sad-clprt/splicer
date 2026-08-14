"""Stage 05: Generate voiceover script using OpenRouter.

Combines VLM beats + audio scenes → 14-20min voiceover script via OpenRouter API.
This is a lightweight local operation (not RunPod) using gpt-4o-mini.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import requests
from loguru import logger
from rich.console import Console

from . import db
from . import s3

console = Console()


def script_generate(film_id: str, vlm_key: str, audio_enrich_key: str) -> str | None:
    """Generate script from VLM beats and audio enrichment.

    Args:
        film_id: unique film identifier
        vlm_key: S3 key for VLM stage3.json output
        audio_enrich_key: S3 key for audio enrichment JSON

    Returns:
        Generated script text if successful, None otherwise
    """
    logger.info(f"[05_script_generate] Generating script from {vlm_key}")

    try:
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            logger.error("OPENROUTER_API_KEY not set in .env")
            return None

        # Download VLM beats
        s3_client = s3.get_s3_client()
        vlm_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        vlm_tmp.close()
        s3.download_s3_with_fallback(s3_client, s3.VOLUME_ID, vlm_key, vlm_tmp.name)
        vlm_data = json.loads(Path(vlm_tmp.name).read_text())
        Path(vlm_tmp.name).unlink()

        # Download audio enrichment
        audio_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        audio_tmp.close()
        s3.download_s3_with_fallback(s3_client, s3.VOLUME_ID, audio_enrich_key, audio_tmp.name)
        audio_data = json.loads(Path(audio_tmp.name).read_text())
        Path(audio_tmp.name).unlink()

        beats = vlm_data.get("beats", [])
        scenes = audio_data.get("scenes", [])

        logger.info(f"Loaded {len(beats)} beats and {len(scenes)} scenes")

        # Build prompt
        prompt = f"""You are writing a 14-20 minute YouTube voiceover script for a movie recap.

Film: I Am Legend (2007)

Narrative beats (visual understanding from VLM):
{json.dumps(beats, indent=2)}

Audio scene structure:
{json.dumps(scenes[:20], indent=2)}

Write a compelling voiceover script that:
1. Covers the main plot in 14-20 minutes
2. Uses natural, engaging language
3. Flows chronologically
4. Highlights key emotional beats
5. Target ~2600 words for 13-minute duration at 200 wpm

Output only the script text, no metadata."""

        # Call OpenRouter
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 6000,
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
        script_text = result["choices"][0]["message"]["content"]

        logger.info(f"Generated script: {len(script_text)} characters")

        # Upload to S3
        script_key = f"films/{film_id}/script.txt"
        script_tmp = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt")
        script_tmp.write(script_text)
        script_tmp.close()

        s3_client.upload_file(script_tmp.name, s3.VOLUME_ID, script_key)
        Path(script_tmp.name).unlink()

        # Register in DB
        script_hash = hashlib.sha256(script_text.encode()).hexdigest()[:16]
        conn = db.init_db()
        conn.execute(
            "INSERT OR REPLACE INTO videos (id, film_id, status, script, script_hash, target_duration_sec, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (film_id, film_id, "script_ready", script_text, script_hash, 780),
        )
        db.upsert_asset(
            conn,
            film_id=film_id,
            kind="script",
            s3_key=script_key,
            bucket=s3.VOLUME_ID,
            size_bytes=len(script_text),
            status="available",
        )
        conn.close()

        console.print(f"[green]✓[/green] Script generated: {script_key} ({len(script_text)} chars)")
        return script_text

    except Exception as e:
        logger.exception(f"script_generate failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python -m src.05_script_generate <film_id> <vlm_key> <audio_enrich_key>")
        sys.exit(1)

    film_id = sys.argv[1]
    vlm_key = sys.argv[2]
    audio_enrich_key = sys.argv[3]

    script = script_generate(film_id, vlm_key, audio_enrich_key)
    sys.exit(0 if script else 1)
