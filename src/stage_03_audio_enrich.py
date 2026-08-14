"""Stage 03: Submit audio enrichment job to RunPod (WhisperX + scene detection).

Input is proxy_480p to minimize cost. Extracts subtitles via WhisperX and detects
scene changes. Output: audio_enrich.json with scenes + transcription data.
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client

console = Console()


def audio_enrich(
    film_id: str,
    proxy_s3_key: str,
    srt_key: str | None = None,
) -> str | None:
    """Submit audio enrichment job to RunPod WhisperX endpoint.

    Args:
        film_id: unique film identifier
        proxy_s3_key: S3 key for 480p proxy video
        srt_key: Optional S3 key for existing subtitle file

    Returns:
        RunPod job_id if submitted successfully, None otherwise
    """
    logger.info(f"[03_audio_enrich] Submitting audio job for {proxy_s3_key}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        audio_endpoint_id = endpoint_ids.get("audio")
        if not audio_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_AUDIO not set in .env")
            return None

        client = runpod_client.RunPodClient(audio_endpoint_id)

        # WhisperX expects s3_key parameter
        input_data = {
            "s3_key": proxy_s3_key,
            "language": None,  # Auto-detect
            "batch_size": 16,
        }
        if srt_key:
            input_data["srt_key"] = srt_key

        job_id = client.run_async(input_data)
        logger.info(f"Audio enrichment job submitted: {job_id}")

        conn = db.init_db()
        db_job_id = db.insert_job(
            conn,
            film_id=film_id,
            kind="audio",
            status="running",
            runpod_job_id=job_id,
        )
        conn.close()

        console.print(f"[green]✓[/green] Audio job submitted: {job_id} (DB: {db_job_id})")
        return job_id

    except Exception as e:
        logger.exception(f"audio_enrich failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.03_audio_enrich <film_id> <proxy_s3_key> [srt_key]")
        sys.exit(1)

    film_id = sys.argv[1]
    proxy_s3_key = sys.argv[2]
    srt_key = sys.argv[3] if len(sys.argv) > 3 else None

    job_id = audio_enrich(film_id, proxy_s3_key, srt_key)
    sys.exit(0 if job_id else 1)
