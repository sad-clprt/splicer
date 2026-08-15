"""
Audio analysis tool - WhisperX transcription via RunPod.

Extracts audio, transcribes with word-level timestamps, and analyzes content.
"""

from pathlib import Path
from typing import Optional, Dict, Any

from ..film_manager import get_film_dir, get_manifest, update_stage_status


def analyze_audio(film_id: str, source: str = "proxy") -> str:
    """
    Submit audio analysis job to RunPod.

    Args:
        film_id: Film identifier
        source: Which video to analyze ("proxy" or "source")

    Returns:
        job_id: RunPod job ID for polling

    TODO:
        - Get video path from manifest
        - Upload to S3 if needed
        - Submit WhisperX job to RunPod
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

    # TODO: Implement RunPod job submission
    # 1. Upload video to S3 (or get existing S3 URL)
    # 2. Submit WhisperX job
    # 3. Store job_id in manifest

    update_stage_status(
        film_id=film_id,
        stage="audio",
        status="in_progress",
        details={"source": source, "message": "TODO: RunPod integration pending"}
    )

    return "TODO_JOB_ID"


def download_transcript(film_id: str, output_url: str) -> Path:
    """
    Download transcript JSON from S3 to film directory.

    Args:
        film_id: Film identifier
        output_url: S3 URL of transcript

    Returns:
        Local path to transcript.json

    TODO:
        - Download from S3
        - Save to films/{film_id}/audio/transcript.json
        - Update manifest
        - Update stage status to completed
    """
    transcript_path = get_film_dir(film_id) / "audio" / "transcript.json"

    # TODO: Implement S3 download

    update_stage_status(
        film_id=film_id,
        stage="audio",
        status="completed",
        details={"transcript_path": "audio/transcript.json", "message": "TODO: Download not implemented"}
    )

    return transcript_path


def enrich_audio(film_id: str) -> Dict[str, Any]:
    """
    Enrich audio analysis with additional metadata.

    Analyzes transcript for key moments, dialogue patterns, pacing.

    Args:
        film_id: Film identifier

    Returns:
        Enrichment data dict

    TODO:
        - Load transcript from audio/transcript.json
        - Analyze for key moments
        - Identify dialogue vs silence
        - Detect pacing patterns
        - Save to audio/enrichment.json
    """
    transcript_path = get_film_dir(film_id) / "audio" / "transcript.json"

    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    # TODO: Implement audio enrichment analysis
    # - Parse transcript
    # - Identify key dialogue
    # - Analyze pacing
    # - Save enrichment data

    enrichment_path = get_film_dir(film_id) / "audio" / "enrichment.json"

    return {
        "status": "TODO",
        "message": "Audio enrichment not implemented"
    }
