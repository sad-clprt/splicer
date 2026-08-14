"""Stage 02: Poll proxy job and download result.

Polls RunPod job until COMPLETED, then downloads 480p proxy from S3.
"""

import pathlib
import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client
from . import s3

console = Console()


def proxy_download(film_id: str, job_id: str, dest_dir: pathlib.Path | str = "./output") -> pathlib.Path | None:
    """Poll proxy job until complete and download result.

    Args:
        film_id: unique film identifier
        job_id: RunPod job ID from 01_proxy_generate
        dest_dir: local directory to save downloaded proxy

    Returns:
        Path to downloaded file if successful, None otherwise
    """
    logger.info(f"[02_proxy_download] Polling job {job_id}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        proxy_endpoint_id = endpoint_ids.get("proxy")
        if not proxy_endpoint_id:
            logger.error("RUNPOD_ENDPOINT_PROXY not set in .env")
            return None

        client = runpod_client.RunPodClient(proxy_endpoint_id)

        # Poll until complete
        console.print(f"Polling job {job_id}...", style="dim")
        result = client.poll_until_complete(job_id, poll_interval=15, max_wait=1800)

        output = result.get("output", {})
        proxy_s3_key = output.get("proxy_key")
        size_bytes = output.get("size_bytes", 0)

        if not proxy_s3_key:
            logger.error(f"Job {job_id} completed but no proxy_key in output: {output}")
            return None

        logger.info(f"Proxy ready: {proxy_s3_key} ({size_bytes:,} bytes)")

        # Download from S3
        dest_path = pathlib.Path(dest_dir) / f"{film_id}_480p.mp4"
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        s3_client = s3.get_s3_client()
        console.print(f"Downloading {proxy_s3_key}...", style="dim")
        s3.download_s3_with_fallback(s3_client, s3.VOLUME_ID, proxy_s3_key, dest_path)

        # Register in DB
        conn = db.init_db()
        db.upsert_asset(
            conn,
            film_id=film_id,
            kind="proxy_480p",
            s3_key=proxy_s3_key,
            bucket=s3.VOLUME_ID,
            s3_endpoint=s3.S3_ENDPOINT,
            datacenter=s3.S3_REGION,
            size_bytes=size_bytes,
            status="available",
        )
        db.update_job(conn, job_id=job_id, status="completed")
        conn.close()

        console.print(f"[green]✓[/green] Proxy downloaded: {dest_path} ({dest_path.stat().st_size:,} bytes)")
        return dest_path

    except Exception as e:
        logger.exception(f"proxy_download failed: {e}")
        conn = db.init_db()
        db.update_job(conn, job_id=job_id, status="failed", error=str(e))
        conn.close()
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.02_proxy_download <film_id> <job_id> [dest_dir]")
        sys.exit(1)

    film_id = sys.argv[1]
    job_id = sys.argv[2]
    dest_dir = sys.argv[3] if len(sys.argv) > 3 else "./output"

    result = proxy_download(film_id, job_id, dest_dir)
    sys.exit(0 if result else 1)
