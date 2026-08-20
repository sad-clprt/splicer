"""
Visual analysis tool - Qwen3-VL frame analysis via Modal.

Analyzes key frames for visual content, cinematography, scene detection.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List

from ..film_manager import get_film_dir, get_manifest, update_stage_status


def analyze_visual(
    film_id: str,
    source: str = "proxy",
    sample_rate: int = 30
) -> str:
    """
    Submit visual analysis job to Modal.

    Args:
        film_id: Film identifier
        source: Which video to analyze ("proxy" or "source")
        sample_rate: Extract one frame every N seconds

    Returns:
        job_id: Modal call ID for polling

    TODO:
        - Get video path from manifest
        - Upload to Modal Volume if needed
        - Submit Qwen3-VL job to Modal
        - Update manifest with job_id and in_progress status
    """
    manifest = get_manifest(film_id)

    if source == "proxy":
        video_file = "proxy.mp4"
    else:
        video_file = manifest.get("files", {}).get("source")

    if not video_file:
        raise ValueError(f"No {source} video found for film: {film_id}")

    video_path = get_film_dir(film_id) / video_file

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # TODO: Implement Modal function submission
    # 1. Upload video to Modal Volume (or get existing Volume path)
    # 2. Submit Qwen3-VL job with sample_rate
    # 3. Store job_id in manifest

    update_stage_status(
        film_id=film_id,
        stage="visual",
        status="in_progress",
        details={"source": source, "sample_rate": sample_rate, "message": "TODO: Modal integration pending"}
    )

    return "TODO_JOB_ID"


def download_visual_analysis(film_id: str, output_url: str) -> Path:
    """
    Download VLM analysis JSON from Modal Volume to film directory.

    Args:
        film_id: Film identifier
        output_url: Volume path of analysis results

    Returns:
        Local path to vlm_output.json

    TODO:
        - Download from Modal Volume
        - Save to films/{film_id}/visual/vlm_output.json
        - Update manifest
        - Update stage status to completed
    """
    output_path = get_film_dir(film_id) / "visual" / "vlm_output.json"

    # TODO: Implement Modal Volume download

    update_stage_status(
        film_id=film_id,
        stage="visual",
        status="completed",
        details={"output_path": "visual/vlm_output.json", "message": "TODO: Download not implemented"}
    )

    return output_path


def get_key_frames(film_id: str, min_score: float = 0.7) -> List[Dict[str, Any]]:
    """
    Get key frames from saved visual analysis.

    Args:
        film_id: Film identifier
        min_score: Minimum importance score (0-1)

    Returns:
        List of key frame dicts with timestamp, description, score

    TODO:
        - Load from visual/vlm_output.json
        - Filter by score
        - Return key frames
    """
    output_path = get_film_dir(film_id) / "visual" / "vlm_output.json"

    if not output_path.exists():
        raise FileNotFoundError(f"Visual analysis not found: {output_path}")

    # TODO: Load and parse vlm_output.json
    # return [frame for frame in frames if frame["score"] >= min_score]

    return []


def get_scene_changes(film_id: str) -> List[float]:
    """
    Get scene change timestamps from visual analysis.

    Args:
        film_id: Film identifier

    Returns:
        List of timestamps (in seconds) where scenes change

    TODO:
        - Load from visual/vlm_output.json
        - Extract scene boundaries
        - Return timestamps
    """
    output_path = get_film_dir(film_id) / "visual" / "vlm_output.json"

    if not output_path.exists():
        raise FileNotFoundError(f"Visual analysis not found: {output_path}")

    # TODO: Load and parse vlm_output.json
    # return scene_change_timestamps

    return []
