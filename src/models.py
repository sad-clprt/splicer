"""Pydantic models for shared data structures."""

from pydantic import BaseModel
from pydantic import Field


class ProxyJob(BaseModel):
    """Input for proxy generation job."""
    s3_key: str = Field(..., description="S3 key for source 1080p film")
    target_width: int = Field(854, description="Target width in pixels")
    target_height: int = Field(480, description="Target height in pixels")
    codec: str = Field("h264_nvenc", description="Video codec")
    crf: int = Field(23, description="Constant Rate Factor for quality")
    preset: str = Field("fast", description="Encoding preset")
    gop_size: int = Field(30, description="GOP size for keyframe interval")


class AudioJob(BaseModel):
    """Input for WhisperX audio transcription job."""
    s3_key: str = Field(..., description="S3 key for video file to transcribe")
    language: str | None = Field(None, description="Language code, None for auto-detect")
    batch_size: int = Field(16, description="Batch size for transcription")


class VLMJob(BaseModel):
    """Input for VLM frame description job."""
    s3_key: str = Field(..., description="S3 key for video file")
    frame_interval: int = Field(8, description="Extract 1 frame per N seconds")
    max_frames: int = Field(675, description="Maximum frames to process")
    model: str = Field("Qwen/Qwen3-VL-8B-Instruct", description="VLM model name")


class TTSJob(BaseModel):
    """Input for TTS generation job."""
    text: str = Field(..., description="Script text to synthesize")
    voice: str = Field("default", description="Voice ID or name")
    speed: float = Field(1.0, description="Speech speed multiplier")


class SafetyJob(BaseModel):
    """Input for safety/content moderation job."""
    s3_key: str = Field(..., description="S3 key for video to check")
    frame_sample_rate: int = Field(30, description="Check 1 frame per N frames")
    model: str = Field("mistralai/Shieldstral-8B-Instruct", description="Safety model")


class FilmMetadata(BaseModel):
    """Film metadata stored in DB."""
    id: str
    title: str
    year: int | None = None
    duration_sec: int | None = None


class AssetMetadata(BaseModel):
    """Asset metadata stored in DB."""
    id: str
    film_id: str
    kind: str
    s3_key: str
    bucket: str | None = None
    size_bytes: int | None = None
    status: str = "available"
