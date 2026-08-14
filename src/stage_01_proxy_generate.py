"""Stage 01: Submit proxy generation job to RunPod.

Submits 1080p → 480p transcoding job to splicer-proxy endpoint.
Does NOT wait for completion — use 02_proxy_download.py to poll and download.
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client

console = Console()


def proxy_generate(film_id: str, source_s3_key: str) -> str | None:
    """Submit proxy generation job to RunPod.

    Args:
        film_id: unique film identifier
        source_s3_key: S3 key for source 1080p file

    Returns:
        RunPod job_id if submitted successfully, None otherwise
    """
    logger.info(f"[01_proxy_generate] Submitting proxy job for {source_s3_key}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        proxy_endpoint_id = endpoint_ids.get("proxy")
        if not proxy_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_PROXY not set in .env")
            return None

        client = runpod_client.RunPodClient(proxy_endpoint_id)

        input_data = {
            "s3_key": source_s3_key,
            "target_width": 854,
            "target_height": 480,
            "codec": "h264_nvenc",
            "crf": 23,
            "preset": "fast",
            "gop_size": 30,
        }

        job_id = client.run_async(input_data)
        logger.info(f"Proxy job submitted: {job_id}")

        conn = db.init_db()
        db_job_id = db.insert_job(
            conn,
            film_id=film_id,
            kind="proxy",
            status="running",
            runpod_job_id=job_id,
        )
        conn.close()

        console.print(f"[green]✓[/green] Proxy job submitted: {job_id} (DB: {db_job_id})")
        return job_id

    except Exception as e:
        logger.exception(f"proxy_generate failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.01_proxy_generate <film_id> <source_s3_key>")
        sys.exit(1)

    film_id = sys.argv[1]
    source_s3_key = sys.argv[2]

    job_id = proxy_generate(film_id, source_s3_key)
    sys.exit(0 if job_id else 1)
