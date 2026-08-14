"""Stage 04: Submit VLM (Vision-Language Model) job for scene understanding.

Processes proxy_480p with Qwen3-VL-8B-Instruct to generate hierarchical scene
descriptions: stage1 (frame clips) → stage2 (scene fusion) → stage3 (narrative beats).
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client

console = Console()


def vlm_generate(
    film_id: str,
    proxy_s3_key: str,
    audio_enrich_key: str | None = None,
) -> str | None:
    """Submit VLM generation job to RunPod.

    Args:
        film_id: unique film identifier
        proxy_s3_key: S3 key for 480p proxy video
        audio_enrich_key: Optional S3 key for audio enrichment JSON

    Returns:
        RunPod job_id if submitted successfully, None otherwise
    """
    logger.info(f"[04_vlm_generate] Submitting VLM job for {proxy_s3_key}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        vlm_endpoint_id = endpoint_ids.get("vlm")
        if not vlm_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_VLM not set in .env")
            return None

        client = runpod_client.RunPodClient(vlm_endpoint_id)

        # VLM worker expects OpenAI-style messages format
        input_data = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this video and describe key scenes."},
                        {"type": "video_url", "video_url": {"url": f"s3://{proxy_s3_key}"}},
                    ],
                }
            ],
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "max_tokens": 4096,
        }

        if audio_enrich_key:
            input_data["audio_enrich_key"] = audio_enrich_key

        job_id = client.run_async(input_data)
        logger.info(f"VLM job submitted: {job_id}")

        conn = db.init_db()
        db_job_id = db.insert_job(
            conn,
            film_id=film_id,
            kind="vlm",
            status="running",
            runpod_job_id=job_id,
        )
        conn.close()

        console.print(f"[green]✓[/green] VLM job submitted: {job_id} (DB: {db_job_id})")
        return job_id

    except Exception as e:
        logger.exception(f"vlm_generate failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.04_vlm_generate <film_id> <proxy_s3_key> [audio_enrich_key]")
        sys.exit(1)

    film_id = sys.argv[1]
    proxy_s3_key = sys.argv[2]
    audio_enrich_key = sys.argv[3] if len(sys.argv) > 3 else None

    job_id = vlm_generate(film_id, proxy_s3_key, audio_enrich_key)
    sys.exit(0 if job_id else 1)
