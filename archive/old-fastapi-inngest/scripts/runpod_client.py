"""RunPod Serverless client — all heavy work goes through here, never local ffmpeg/GPU.

Helpers for the 5 provisioned endpoints (workers 0/0 scaled on demand):
  proxy 2dmz605z5wxjo1 (runpod/base → cloud-build Dockerfile needed),
  audio 0jj6liixhjnhbh (hapnan-whisperx),
  tts   5fb99jvt01k63a (chatterbox),
  vlm   i5xjuwuikr335p (worker-vllm Qwen3-VL-8B),
  safety yams2crmm7o6l9 (worker-vllm Shieldstral).

Usage:
  from scripts.runpod_client import run_sync, scale_endpoint

  out = run_sync("2dmz605z5wxjo1", {"s3_key": "...", "proxy_key": "..."}, timeout=1800)
"""

from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

ENDPOINTS = {
    "proxy": "2dmz605z5wxjo1",
    "audio": "0jj6liixhjnhbh",
    "tts": "5fb99jvt01k63a",
    "vlm": "i5xjuwuikr335p",
    "safety": "yams2crmm7o6l9",
}

RUNPOD_API_BASE = "https://api.runpod.ai/v2"


def get_api_key() -> str:
    k = os.getenv("RUNPOD_API_KEY") or ""
    k = k.strip().strip('"').strip("'")
    if not k:
        raise RuntimeError("RUNPOD_API_KEY missing in .env")
    return k


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"}


def get_endpoint_health(endpoint_id: str) -> dict:
    """GET /v2/{id}/health — never raises, returns dict with jobs/health."""
    try:
        r = requests.get(f"{RUNPOD_API_BASE}/{endpoint_id}/health", headers=_headers(), timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "endpoint": endpoint_id}


def scale_endpoint(endpoint_id: str, workers_max: int = 1, workers_min: int = 0) -> dict:
    """Scale via RunPod MCP update-endpoint (GraphQL) — correct path vs raw PATCH /v2.

    Uses the same MCP server the handoff verifies (npx @runpod/mcp-server) to avoid
    404 on raw PATCH. Falls back to direct PATCH if MCP unavailable.
    Returns json or {error}.
    """
    # Primary: MCP update-endpoint (handles GraphQL mutation + auth)
    try:
        import json
        import subprocess

        key = get_api_key()
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "update-endpoint", "arguments": {"endpointId": endpoint_id, "workersMax": workers_max, "workersMin": workers_min}},
            }
        )
        # run MCP stdio bridge
        proc = subprocess.run(
            ["npx", "-y", "@runpod/mcp-server@latest"],
            input=(payload + "\n").encode(),
            env={**os.environ, "RUNPOD_API_KEY": key},
            capture_output=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            try:
                out = json.loads(proc.stdout.decode().splitlines()[-1])
                # MCP returns {result: {content: [{text: "{...}"}]}}
                text = out.get("result", {}).get("content", [{}])[0].get("text", "")
                if text:
                    return json.loads(text)
                return out
            except Exception:
                return {"mcp_raw": proc.stdout.decode()[:1000]}
        # fallback to raw PATCH if MCP failed
    except Exception as e:
        # will try fallback
        pass
    try:
        r = requests.patch(
            f"{RUNPOD_API_BASE}/{endpoint_id}",
            headers=_headers(),
            json={"workersMax": workers_max, "workersMin": workers_min},
            timeout=15,
        )
        if r.status_code in (200, 201, 204):
            try:
                return r.json() if r.content else {"status": r.status_code}
            except Exception:
                return {"status": r.status_code}
        return {"error": f"scale {r.status_code}: {r.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def purge_queue(endpoint_id: str) -> dict:
    """POST /v2/{id}/purge-queue — best effort."""
    try:
        r = requests.post(f"{RUNPOD_API_BASE}/{endpoint_id}/purge-queue", headers=_headers(), timeout=15)
        if r.status_code in (200, 204):
            try:
                return r.json() if r.content else {"purged": True}
            except Exception:
                return {"purged": True}
        return {"error": f"purge {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def run_endpoint(endpoint_id: str, payload: dict) -> str:
    """POST /v2/{endpointId}/run → returns jobId/id. Raises on HTTP error."""
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/run"
    r = requests.post(url, headers=_headers(), json={"input": payload}, timeout=30)
    r.raise_for_status()
    j = r.json()
    # RunPod returns {"id": "...", "status": "IN_QUEUE"} or {"jobId": "..."}
    job_id = j.get("id") or j.get("jobId") or j.get("job_id") or ""
    if not job_id and isinstance(j, dict):
        # sometimes nested
        job_id = j.get("data", {}).get("id", "") if isinstance(j.get("data"), dict) else ""
    if not job_id:
        raise RuntimeError(f"run returned no job id: {j}")
    return str(job_id)


def get_job_status(endpoint_id: str, job_id: str) -> dict:
    """GET /v2/{endpointId}/status/{jobId} → full status dict."""
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/status/{job_id}"
    r = requests.get(url, headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def run_sync(
    endpoint_id: str,
    payload: dict,
    timeout: int = 1800,
    poll_interval: int = 15,
    ensure_scaled: bool = True,
    verbose: bool = True,
) -> dict:
    """Run + poll until COMPLETED/FAILED. Optionally scales workersMax=1 before run.

    Returns raw status dict on COMPLETED (with output).
    Raises RuntimeError/TimeoutError on FAILED/timeout.
    """
    if ensure_scaled:
        scale_endpoint(endpoint_id, workers_max=1, workers_min=0)

    job_id = run_endpoint(endpoint_id, payload)
    if verbose:
        print(f"[runpod] endpoint {endpoint_id} job {job_id} queued input_keys={list(payload.keys())}")

    start = time.time()
    last_status = ""
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            raise TimeoutError(f"RunPod job {job_id} timed out after {timeout}s on {endpoint_id} last_status={last_status}")
        time.sleep(poll_interval)
        st = get_job_status(endpoint_id, job_id)
        # status can be at top level or nested
        status = st.get("status") or st.get("state") or ""
        # streaming cases may have st["status"] == "IN_PROGRESS" etc
        if isinstance(status, str):
            status_u = status.upper()
        else:
            status_u = ""
        # also check st itself for COMPLETED/FAILED strings
        if verbose and status_u != last_status:
            print(f"[runpod] {endpoint_id}/{job_id} {status_u} elapsed={int(time.time()-start)}s")
            last_status = status_u
        if status_u == "COMPLETED":
            return st
        if status_u == "FAILED":
            err = st.get("error") or st.get("output") or st
            raise RuntimeError(f"RunPod job {job_id} FAILED: {err}")
        # keep polling for IN_QUEUE / IN_PROGRESS / None
        # also treat explicit output with completed marker
        # some hubs return output even with status missing — treat non-empty output as completed only if no error


def run_sync_by_name(
    name: str,
    payload: dict,
    timeout: int = 1800,
    poll_interval: int = 15,
    ensure_scaled: bool = True,
) -> dict:
    """Convenience by logical name (proxy/audio/vlm/tts/safety)."""
    eid = ENDPOINTS.get(name)
    if not eid:
        raise ValueError(f"unknown endpoint name {name} not in {list(ENDPOINTS)}")
    return run_sync(eid, payload, timeout=timeout, poll_interval=poll_interval, ensure_scaled=ensure_scaled)
