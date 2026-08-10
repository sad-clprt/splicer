"""Core metadata tables — blobs live on RunPod S3/Network Volume, only pointers here."""

import uuid
from datetime import UTC
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

# Enums as strings for portability (SQLite fallback in tests)
AssetKind = Enum(
    "source_1080p",
    "proxy_480p",
    "final_1080p",
    "subtitle",
    "thumbnail",
    name="asset_kind",
)
VideoStatus = Enum(
    "draft",
    "proxying",
    "scenes",
    "safety",
    "scripting",
    "tts",
    "assembling",
    "ready",
    "published",
    name="video_status",
)
JobKind = Enum(
    "proxy",
    "scene_detect",
    "safety",
    "script",
    "tts",
    "assemble",
    name="job_kind",
)
JobStatus = Enum(
    "queued",
    "running",
    "completed",
    "failed",
    name="job_status",
)


class Film(Base):
    """Source material — e.g. 'I Am Legend' (2007, Francis Lawrence)."""

    __tablename__ = "films"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(300), nullable=False, index=True)
    year = Column(Integer, nullable=True)
    director = Column(String(200), nullable=True)
    cast = Column(JSONB, nullable=True)  # ["Will Smith", ...]
    tmdb_id = Column(String(50), nullable=True, unique=True)
    imdb_id = Column(String(20), nullable=True, unique=True)
    duration_sec = Column(Integer, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )

    assets = relationship("Asset", back_populates="film", cascade="all, delete-orphan")
    videos = relationship("Video", back_populates="film", cascade="all, delete-orphan")


class Asset(Base):
    """Pointer to a blob on RunPod — never store bytes in Postgres."""

    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    film_id = Column(
        UUID(as_uuid=True), ForeignKey("films.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(AssetKind, nullable=False, index=True)
    # RunPod S3 / Network Volume location
    runpod_volume_id = Column(String(100), nullable=True)
    s3_key = Column(String(500), nullable=False)  # e.g. films/<film_id>/proxy_480p.mp4
    s3_endpoint = Column(String(300), nullable=True)  # https://s3api-eu-ro-1.runpod.io/
    datacenter = Column(String(50), nullable=True)  # EU-RO-1
    size_bytes = Column(Integer, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    codec = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="available")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    film = relationship("Film", back_populates="assets")


class Video(Base):
    """Recap output — 12-14 min (720-840s) target."""

    __tablename__ = "videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    film_id = Column(
        UUID(as_uuid=True), ForeignKey("films.id", ondelete="CASCADE"), nullable=False, index=True
    )
    final_asset_id = Column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(VideoStatus, nullable=False, default="draft", index=True)
    target_duration_sec = Column(Integer, nullable=False, default=780)  # 13 min
    script = Column(Text, nullable=True)
    script_hash = Column(String(100), nullable=True)
    youtube_video_id = Column(String(50), nullable=True, unique=True)
    youtube_channel_id = Column(String(100), nullable=True)
    youtube_views = Column(Integer, nullable=True)
    youtube_comments = Column(Integer, nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )

    film = relationship("Film", back_populates="videos")
    final_asset = relationship("Asset")


class Job(Base):
    """Inngest run mirror — for GET /jobs/{id} polling."""

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind = Column(JobKind, nullable=False, index=True)
    status = Column(JobStatus, nullable=False, default="queued", index=True)
    inngest_run_id = Column(String(200), nullable=True)
    runpod_job_id = Column(String(200), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )
