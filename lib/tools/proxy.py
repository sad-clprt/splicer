"""
Proxy generation tool - PyNvVideoCodec transcode to 480p via RunPod.

Transcodes source video to 480p for faster analysis and editing.
"""

import os
import time
from pathlib import Path
from typing import Optional, Dict, Any

import runpod
from dotenv import load_dotenv

from ..film_manager import get_film_dir, get_manifest, update_stage_status
from . import storage

load_dotenv()

RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_PROXY")
VOLUME_ID = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")


def s3_key_for_film(film_id: str, filename: str) -> str:
    """Generate S3 key for a film file."""
    return f"films/{film_id}/{filename}"


def generate_proxy(film_id: str) -> str:
    """
    Submit proxy generation job to RunPod.

    Args:
        film_id: Film identifier

    Returns:
        job_id: RunPod job ID for polling
    """
    if not RUNPOD_ENDPOINT_ID:
        raise ValueError("RUNPOD_PROXY_ENDPOINT_ID not set in environment")
    
    manifest = get_manifest(film_id)
    source_file = manifest.get("files", {}).get("source")

    if not source_file:
        raise ValueError(f"No source file found for film: {film_id}")

    source_path = get_film_dir(film_id) / source_file

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Upload source to S3 if not already there
    s3_key = s3_key_for_film(film_id, source_file)
    
    print(f"Uploading {source_path.name} to S3...")
    storage.upload_file(str(source_path), s3_key, bucket=VOLUME_ID)
    print(f"Uploaded to s3://{VOLUME_ID}/{s3_key}")

    # Submit job to RunPod
    runpod.api_key = os.getenv("RUNPOD_API_KEY")
    endpoint = runpod.Endpoint(RUNPOD_ENDPOINT_ID)
    
    print(f"Submitting proxy generation job...")
    job = endpoint.run({
        "s3_key": s3_key,
        "proxy_key": s3_key_for_film(film_id, "proxy_480p.mp4")
    })
    
    job_id = job.job_id
    print(f"Job submitted: {job_id}")

    # Update manifest
    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="in_progress",
        details={
            "job_id": job_id,
            "s3_key": s3_key,
            "message": "Transcoding to 480p on RunPod"
        }
    )

    return job_id


def poll_proxy(film_id: str, job_id: str) -> Dict[str, Any]:
    """
    Poll RunPod job status.

    Args:
        film_id: Film identifier
        job_id: RunPod job ID

    Returns:
        Status dict with: status, proxy_key (if completed), error (if failed)
    """
    if not RUNPOD_ENDPOINT_ID:
        raise ValueError("RUNPOD_ENDPOINT_PROXY not set in environment")
    
    runpod.api_key = os.getenv("RUNPOD_API_KEY")
    endpoint = runpod.Endpoint(RUNPOD_ENDPOINT_ID)
    
    # The job_id from endpoint.run() is actually the run_request object's ID
    # We need to create a mock run_request to check status
    # Use the status check API directly
    import requests
    
    api_key = os.getenv("RUNPOD_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"}
    status_url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status/{job_id}"
    
    response = requests.get(status_url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    result = {
        "status": data.get("status"),  # IN_QUEUE, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, TIMED_OUT
    }
    
    if data.get("status") == "COMPLETED":
        output = data.get("output", {})
        result.update({
            "proxy_key": output.get("proxy_key"),
            "width": output.get("width"),
            "height": output.get("height"),
            "duration_seconds": output.get("duration_seconds"),
            "size_bytes": output.get("size_bytes"),
        })
    elif data.get("status") == "FAILED":
        result["error"] = data.get("error") or "Unknown error"
    
    return result


def download_proxy(film_id: str, proxy_key: str) -> Path:
    """
    Download proxy video from S3 to film directory.

    Args:
        film_id: Film identifier
        proxy_key: S3 key of generated proxy

    Returns:
        Local path to downloaded proxy
    """
    proxy_path = get_film_dir(film_id) / "proxy_480p.mp4"
    
    print(f"Downloading proxy from S3...")
    storage.download_file(proxy_key, str(proxy_path), bucket=VOLUME_ID, use_api_key=True)
    
    print(f"Downloaded to {proxy_path}")

    # Update manifest
    manifest = get_manifest(film_id)
    manifest.setdefault("files", {})["proxy"] = "proxy_480p.mp4"
    
    # Write manifest
    manifest_path = get_film_dir(film_id) / "manifest.json"
    import json
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="completed",
        details={"proxy_path": "proxy_480p.mp4"}
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
    """
    job_id = generate_proxy(film_id)
    
    print(f"Polling for completion (timeout: {timeout}s)...")
    elapsed = 0
    
    while elapsed < timeout:
        status = poll_proxy(film_id, job_id)
        
        if status["status"] == "COMPLETED":
            print(f"Job completed!")
            return download_proxy(film_id, status["proxy_key"])
        elif status["status"] in ("FAILED", "CANCELLED", "TIMED_OUT"):
            error_msg = status.get("error", "Unknown error")
            raise RuntimeError(f"Proxy generation {status['status'].lower()}: {error_msg}")
        
        print(f"Status: {status['status']} (elapsed: {elapsed}s)")
        time.sleep(poll_interval)
        elapsed += poll_interval
    
    raise TimeoutError(f"Proxy generation timed out after {timeout}s")
