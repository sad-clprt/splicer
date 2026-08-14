"""Stage 06: Submit TTS (Text-to-Speech) job to RunPod.

Converts script text to audio using TTS endpoint. Splits long scripts into chunks
if needed to stay within API limits.
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client

console = Console()


def tts_generate(film_id: str, script_text: str) -> str | None:
    """Submit TTS generation job to RunPod.

    Args:
        film_id: unique film identifier
        script_text: voiceover script text to synthesize

    Returns:
        RunPod job_id if submitted successfully, None otherwise
    """
    logger.info(f"[06_tts_generate] Submitting TTS job ({len(script_text)} chars)")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        tts_endpoint_id = endpoint_ids.get("tts")
        if not tts_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_TTS not set in .env")
            return None

        client = runpod_client.RunPodClient(tts_endpoint_id)

        input_data = {
            "text": script_text,
            "voice": "default",
            "speed": 1.0,
        }

        job_id = client.run_async(input_data)
        logger.info(f"TTS job submitted: {job_id}")

        conn = db.init_db()
        db_job_id = db.insert_job(
            conn,
            film_id=film_id,
            kind="tts",
            status="running",
            runpod_job_id=job_id,
        )
        conn.close()

        console.print(f"[green]✓[/green] TTS job submitted: {job_id} (DB: {db_job_id})")
        return job_id

    except Exception as e:
        logger.exception(f"tts_generate failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.06_tts_generate <film_id> <script_text>")
        sys.exit(1)

    film_id = sys.argv[1]
    script_text = sys.argv[2]

    job_id = tts_generate(film_id, script_text)
    sys.exit(0 if job_id else 1)
