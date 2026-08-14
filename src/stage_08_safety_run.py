"""Stage 08: Run safety check on final video.

Submits final video to RunPod safety endpoint (Shieldstral-8B-Instruct) for
content moderation. Samples frames and checks for policy violations.
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client

console = Console()


def safety_run(film_id: str, final_s3_key: str) -> str | None:
    """Submit safety check job to RunPod.

    Args:
        film_id: unique film identifier
        final_s3_key: S3 key for final assembled video

    Returns:
        RunPod job_id if submitted successfully, None otherwise
    """
    logger.info(f"[08_safety_run] Submitting safety check for {final_s3_key}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        safety_endpoint_id = endpoint_ids.get("safety")
        if not safety_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_SAFETY not set in .env")
            return None

        client = runpod_client.RunPodClient(safety_endpoint_id)

        # Safety worker uses same vLLM format as VLM
        input_data = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Check this video for content policy violations."},
                        {"type": "video_url", "video_url": {"url": f"s3://{final_s3_key}"}},
                    ],
                }
            ],
            "model": "mistralai/Shieldstral-8B-Instruct",
            "max_tokens": 2048,
            "frame_sample_rate": 30,  # Check 1 frame per 30 frames
        }

        job_id = client.run_async(input_data)
        logger.info(f"Safety check job submitted: {job_id}")

        conn = db.init_db()
        db_job_id = db.insert_job(
            conn,
            film_id=film_id,
            kind="safety",
            status="running",
            runpod_job_id=job_id,
        )
        conn.close()

        console.print(f"[green]✓[/green] Safety job submitted: {job_id} (DB: {db_job_id})")
        return job_id

    except Exception as e:
        logger.exception(f"safety_run failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.08_safety_run <film_id> <final_s3_key>")
        sys.exit(1)

    film_id = sys.argv[1]
    final_s3_key = sys.argv[2]

    job_id = safety_run(film_id, final_s3_key)
    sys.exit(0 if job_id else 1)
