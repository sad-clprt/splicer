"""
Proxy generation tool - FFmpeg transcode to 480p via RunPod.

Transcodes source video to 480p for faster analysis and editing.
"""

from pathlib import Path
from typing import Optional, Dict, Any

from ..film_manager import get_film_dir, get_manifest, update_stage_status


def generate_proxy(film_id: str) -> str:
    """
    Submit proxy generation job to RunPod.

    Args:
        film_id: Film identifier

    Returns:
        job_id: RunPod job ID for polling

    TODO:
        - Load source video path from manifest
        - Upload to S3 if not already there
        - Submit job to RunPod proxy handler
        - Update manifest with job_id and in_progress status
    """
    manifest = get_manifest(film_id)
    source_file = manifest.get("files", {}).get("source")

    if not source_file:
        raise ValueError(f"No source file found for film: {film_id}")

    source_path = get_film_dir(film_id) / source_file

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # TODO: Implement RunPod job submission
    # 1. Upload source to S3 (or get existing S3 URL)
    # 2. Submit job with: runpod.run_sync(endpoint_id, {"source_url": s3_url})
    # 3. Store job_id in manifest

    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="in_progress",
        details={"message": "TODO: RunPod integration pending"}
    )

    return "TODO_JOB_ID"


def poll_proxy(film_id: str, job_id: str) -> Dict[str, Any]:
    """
    Poll RunPod job status.

    Args:
        film_id: Film identifier
        job_id: RunPod job ID

    Returns:
        Status dict with: status, output_url (if completed)

    TODO:
        - Poll RunPod job status
        - Return {"status": "IN_PROGRESS|COMPLETED|FAILED", "output_url": ...}
    """
    # TODO: Implement RunPod polling
    # status = runpod.status(endpoint_id, job_id)
    # return status

    return {
        "status": "TODO",
        "message": "RunPod polling not implemented"
    }


def download_proxy(film_id: str, output_url: str) -> Path:
    """
    Download proxy video from S3 to film directory.

    Args:
        film_id: Film identifier
        output_url: S3 URL of generated proxy

    Returns:
        Local path to downloaded proxy

    TODO:
        - Download from S3
        - Save to films/{film_id}/proxy.mp4
        - Update manifest with proxy filename
        - Update stage status to completed
    """
    proxy_path = get_film_dir(film_id) / "proxy.mp4"

    # TODO: Implement S3 download
    # s3_client.download_file(bucket, key, proxy_path)

    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="completed",
        details={"proxy_path": "proxy.mp4", "message": "TODO: Download not implemented"}
    )

    return proxy_path


def generate_and_wait(film_id: str, poll_interval: int = 10, timeout: int = 600) -> Path:
    """
    Generate proxy and wait for completion.

    Convenience function that submits job, polls, and downloads.

    Args:
        film_id: Film identifier
        poll_interval: Seconds between polls
        timeout: Maximum wait time in seconds

    Returns:
        Local path to downloaded proxy

    TODO:
        - Implement polling loop
        - Handle timeout
        - Return downloaded proxy path
    """
    job_id = generate_proxy(film_id)

    # TODO: Implement polling loop
    # while elapsed < timeout:
    #     status = poll_proxy(film_id, job_id)
    #     if status["status"] == "COMPLETED":
    #         return download_proxy(film_id, status["output_url"])
    #     elif status["status"] == "FAILED":
    #         raise RuntimeError("Proxy generation failed")
    #     time.sleep(poll_interval)

    raise NotImplementedError("Polling loop not implemented")
