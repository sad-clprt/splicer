"""RunPod Python SDK client wrapper.

Unified interface for submitting jobs to RunPod Serverless endpoints and polling status.
"""

import os
import time
from typing import Any

import runpod
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

runpod.api_key = os.getenv("RUNPOD_API_KEY")


class RunPodClient:
    """Wrapper around runpod SDK for job submission and polling."""

    def __init__(self, endpoint_id: str):
        self.endpoint_id = endpoint_id
        self.endpoint = runpod.Endpoint(endpoint_id)

    def run_sync(self, input_data: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
        """Submit job and wait up to timeout seconds. Returns result or job status if timeout."""
        try:
            result = self.endpoint.run_sync(input_data)
            return result
        except Exception as e:
            logger.error(f"RunPod sync call failed for {self.endpoint_id}: {e}")
            raise

    def run_async(self, input_data: dict[str, Any]) -> str:
        """Submit job asynchronously, return job_id immediately."""
        try:
            run_request = self.endpoint.run(input_data)
            return run_request.job_id
        except Exception as e:
            logger.error(f"RunPod async submission failed for {self.endpoint_id}: {e}")
            raise

    def poll_until_complete(
        self, job_id: str, poll_interval: int = 15, max_wait: int = 1800
    ) -> dict[str, Any]:
        """Poll job status until COMPLETED, FAILED, or max_wait seconds."""
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(f"Job {job_id} did not complete within {max_wait}s")

            status_response = self.endpoint.status(job_id)
            status = status_response.get("status")
            logger.debug(f"Job {job_id} status={status} elapsed={elapsed:.1f}s")

            if status == "COMPLETED":
                return status_response
            elif status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                error = status_response.get("error", "Unknown error")
                raise RuntimeError(f"Job {job_id} {status}: {error}")

            time.sleep(poll_interval)

    def health(self) -> dict[str, Any]:
        """Get endpoint health status."""
        # Note: runpod SDK may not expose health directly, use REST API if needed
        import requests

        api_key = os.getenv("RUNPOD_API_KEY")
        url = f"https://api.runpod.ai/v2/{self.endpoint_id}/health"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()


def get_endpoint_ids() -> dict[str, str]:
    """Return mapping of endpoint names to IDs from environment."""
    return {
        "proxy": os.getenv("RUNPOD_ENDPOINT_PROXY", ""),
        "audio": os.getenv("RUNPOD_ENDPOINT_AUDIO", ""),
        "vlm": os.getenv("RUNPOD_ENDPOINT_VLM", ""),
        "tts": os.getenv("RUNPOD_ENDPOINT_TTS", ""),
        "safety": os.getenv("RUNPOD_ENDPOINT_SAFETY", ""),
    }
