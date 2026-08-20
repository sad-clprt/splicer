"""
Proxy generation tool - 1080p → 480p transcode via Modal.

Uses Modal Volume `splicer-films` mounted at /films and Function `splicer:transcode_proxy`.
Replaces previous RunPod + S3 implementation.
"""

import time
from pathlib import Path
from typing import Dict, Any

from ..film_manager import get_film_dir, get_manifest, update_stage_status


VOLUME_NAME = "splicer-films"
VOLUME_MOUNT = "/films"  # must match modal_app/app.py


def _upload_source_to_volume(film_id: str, source_path: Path) -> None:
    """Ensure source video is present on Modal Volume. Upload if missing."""
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required for proxy generation. Install with `uv add modal`") from e

    vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
    volume_path = f"{film_id}/{source_path.name}"
    # Check if already exists on volume
    try:
        exists = any(vol.listdir(volume_path))
        # listdir on file returns file info; on missing it raises or empty
        # Safer: try iterdir
        if exists:
            return
    except Exception:
        pass

    # Use batch_upload to put file
    # volume_path should be without leading slash, e.g. "i_am_legend_ed264664/source.mp4"
    # Ensure parent dir exists via batch_upload putting file
    with vol.batch_upload() as batch:
        batch.put_file(str(source_path), f"/{volume_path}")
    # Commit is handled by batch_upload context


def volume_key_for_film(film_id: str, filename: str) -> str:
    """Generate Volume key for a film file (e.g. films/film_id/file). Used for manifest consistency."""
    return f"{film_id}/{filename}"


def s3_key_for_film(film_id: str, filename: str) -> str:
    """Legacy alias for volume_key_for_film — kept for backwards compat."""
    return volume_key_for_film(film_id, filename)


def generate_proxy(film_id: str, source_filename: str | None = None, overwrite: bool = False) -> str:
    """
    Submit proxy generation job to Modal (async).

    Args:
        film_id: Film identifier
        source_filename: Optional source override
        overwrite: Re-transcode even if proxy exists

    Returns:
        call_id: Modal FunctionCall ID for polling
    """
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required. Install with `pip install modal`") from e

    manifest = get_manifest(film_id)
    source_file = source_filename or manifest.get("files", {}).get("source")

    if not source_file:
        raise ValueError(f"No source file found for film: {film_id}")

    source_path = get_film_dir(film_id) / source_file
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Upload source to Modal Volume if not already there (best-effort)
    try:
        _upload_source_to_volume(film_id, source_path)
    except Exception as e:
        # Don't fail submission if upload fails — function will try to read from volume
        # but we log for debugging
        print(f"Warning: failed to upload source to Volume: {e}")

    # Spawn Modal function
    func = modal.Function.from_name("splicer", "transcode_proxy")
    call = func.spawn(film_id, source_filename=source_file, overwrite=overwrite)
    call_id = call.object_id

    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="in_progress",
        details={"call_id": call_id, "source": str(source_path), "message": "Transcoding to 480p on Modal"},
    )

    return call_id


def poll_proxy(film_id: str, job_id: str) -> Dict[str, Any]:
    """
    Poll Modal job status.

    Args:
        film_id: Film identifier (unused, kept for API compat)
        job_id: Modal call ID (from generate_proxy)

    Returns:
        dict with status: IN_PROGRESS | COMPLETED | FAILED, plus metadata when completed
    """
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required") from e

    call = modal.FunctionCall.from_id(job_id)
    try:
        output = call.get(timeout=0)
        # Completed
        result = {"status": "COMPLETED"}
        if isinstance(output, dict):
            result.update(output)
        else:
            result["output"] = output
        return result
    except TimeoutError:
        return {"status": "IN_PROGRESS"}
    except Exception as e:
        return {"status": "FAILED", "error": str(e)}


def download_proxy(film_id: str, proxy_key: str | None = None) -> Path:
    """
    Download proxy video from Modal Volume to local film directory.

    Args:
        film_id: Film identifier
        proxy_key: Volume path (e.g. "i_am_legend_ed264664/proxy_480p.mp4"). If None, uses "proxy_480p.mp4"

    Returns:
        Local path to downloaded proxy
    """
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required") from e

    if proxy_key and proxy_key.startswith(f"{VOLUME_MOUNT}/"):
        proxy_key = proxy_key[len(VOLUME_MOUNT) + 1 :]
    if proxy_key and proxy_key.startswith("films/"):
        proxy_key = proxy_key[len("films/") :]
    # Normalize: if proxy_key contains film_id prefix, keep as is, else prepend
    if proxy_key:
        # If proxy_key already like "film_id/proxy_480p.mp4", use as is
        if "/" in proxy_key and not proxy_key == "proxy_480p.mp4":
            volume_path = proxy_key if proxy_key.startswith(film_id) else f"{film_id}/{proxy_key}"
        else:
            volume_path = f"{film_id}/{proxy_key}"
    else:
        volume_path = f"{film_id}/proxy_480p.mp4"

    # Local destination — mimic film_manager structure
    local_path = get_film_dir(film_id) / "proxy_480p.mp4"
    local_path.parent.mkdir(parents=True, exist_ok=True)

    vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

    # Download via read_file iterator (handles large files)
    # Volume path must be absolute with leading slash
    remote_path = f"/{volume_path}"
    print(f"Downloading proxy from Volume {remote_path} -> {local_path} ...")
    with open(local_path, "wb") as f:
        for chunk in vol.read_file(remote_path):
            f.write(chunk)

    size_bytes = local_path.stat().st_size
    print(f"Downloaded {size_bytes / (1024*1024):.2f} MB to {local_path}")

    # Update manifest to reflect local availability
    manifest = get_manifest(film_id)
    manifest.setdefault("files", {})["proxy"] = "proxy_480p.mp4"
    manifest_path = get_film_dir(film_id) / "manifest.json"
    import json

    # Use film_manager helper to keep consistency, but also ensure files.proxy set
    manifest["files"]["proxy"] = "proxy_480p.mp4"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    update_stage_status(
        film_id=film_id,
        stage="proxy",
        status="completed",
        details={"proxy_path": "proxy_480p.mp4", "size_bytes": size_bytes, "volume_path": volume_path},
    )

    return local_path


def generate_and_wait(
    film_id: str, poll_interval: int = 10, timeout: int = 3600, overwrite: bool = False
) -> Path:
    """
    Generate proxy and wait for completion (blocking).

    Args:
        film_id: Film identifier
        poll_interval: Seconds between polls
        timeout: Maximum wait time
        overwrite: Force retranscode

    Returns:
        Local path to downloaded proxy
    """
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required") from e

    # For simpler wait, use synchronous remote with timeout
    # Option 1: spawn + poll loop (allows progress prints)
    call_id = generate_proxy(film_id, overwrite=overwrite)
    print(f"Proxy job spawned: {call_id}, polling every {poll_interval}s (timeout {timeout}s)...")
    elapsed = 0
    while elapsed < timeout:
        status = poll_proxy(film_id, call_id)
        if status["status"] == "COMPLETED":
            print("Job completed, downloading...")
            proxy_key = status.get("proxy_path") or f"{film_id}/proxy_480p.mp4"
            return download_proxy(film_id, proxy_key)
        elif status["status"] == "FAILED":
            raise RuntimeError(f"Proxy generation failed: {status.get('error')}")
        print(f"Status: {status['status']} (elapsed {elapsed}s)")
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"Proxy generation timed out after {timeout}s (call_id={call_id})")


def transcode_proxy_sync(film_id: str, overwrite: bool = False) -> dict:
    """
    Synchronous variant that directly calls Modal function and returns metadata without downloading.

    Useful when you only need metadata and want Volume to retain file.
    """
    import modal

    func = modal.Function.from_name("splicer", "transcode_proxy")
    result = func.remote(film_id, overwrite=overwrite)
    return result
