"""Neon Postgres connection via SQLAlchemy + psycopg3.

- App runtime uses pooled DATABASE_URL (with -pooler) for high concurrency.
- Alembic migrations should use direct DATABASE_URL (without -pooler) to avoid pooler errors.
- FastAPI Cloud injects DATABASE_URL automatically via Neon integration.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _get_database_url(*, pooled: bool = True) -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    # Derive direct from pooled by removing "-pooler" if requested
    if not pooled and "-pooler" in url:
        url = url.replace("-pooler", "")
    if pooled and "-pooler" not in url and "neon.tech" in url:
        # If only direct is set and pooled requested, we still return direct (works but less pooled)
        pass
    # Use psycopg3 driver for SQLAlchemy 2.0
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _get_database_url(pooled=True)
DATABASE_URL_DIRECT = _get_database_url(pooled=False)

# psycopg3 engine — connect_args for Neon requires sslmode
engine = None
SessionLocal = None

if DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields DB session, handles missing DB gracefully."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL not set — cannot connect to Neon")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
