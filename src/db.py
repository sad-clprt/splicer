"""SQLite helper for splicer pipeline.

All heavy work stays on RunPod; this DB is only pointers + job mirror.
No ORM — raw sqlite3. File lives at src/splicer.db (can be recreated).

Tables:
  films(id TEXT PK, title TEXT, year INT, metadata_json TEXT, duration_sec INT, created_at TEXT, updated_at TEXT)
  assets(id TEXT PK, film_id TEXT FK, kind TEXT, s3_key TEXT UNIQUE, bucket TEXT, size_bytes INT, status TEXT, created_at TEXT)
  videos(id TEXT PK, film_id TEXT FK, status TEXT, script TEXT, script_hash TEXT, target_duration_sec INT, created_at TEXT, updated_at TEXT)
  jobs(id TEXT PK, film_id TEXT, video_id TEXT, kind TEXT, status TEXT, runpod_job_id TEXT, error TEXT, created_at TEXT, updated_at TEXT)
"""

from __future__ import annotations

import pathlib
import sqlite3
import uuid
from datetime import UTC
from datetime import datetime

DB_PATH = pathlib.Path(__file__).parent / "splicer.db"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_conn(db_path: pathlib.Path | str | None = None) -> sqlite3.Connection:
    """Open SQLite connection with FKs enabled. Creates parent dirs."""
    p = pathlib.Path(db_path) if db_path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection | None = None, db_path: pathlib.Path | str | None = None) -> sqlite3.Connection:
    """Create tables if missing. Returns open connection."""
    c = conn or get_conn(db_path)
    # films
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS films (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            year INTEGER,
            metadata_json TEXT,
            duration_sec INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        );
        """
    )
    # assets
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN (
                'source_1080p','proxy_480p','final_1080p','subtitle',
                'audio_enrich','vlm','script','tts','edit_decision','safety','thumbnail'
            )),
            s3_key TEXT NOT NULL,
            bucket TEXT,
            s3_endpoint TEXT,
            datacenter TEXT,
            size_bytes INTEGER,
            duration_sec INTEGER,
            codec TEXT,
            status TEXT NOT NULL DEFAULT 'available',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(s3_key)
        );
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_assets_film ON assets(film_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_assets_s3key ON assets(s3_key);")
    # videos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
            final_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            script TEXT,
            script_hash TEXT,
            target_duration_sec INTEGER DEFAULT 780,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        );
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_videos_film ON videos(film_id);")
    # jobs
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            film_id TEXT REFERENCES films(id) ON DELETE CASCADE,
            video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            runpod_job_id TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        );
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
    return c


def ensure_film(
    conn: sqlite3.Connection,
    film_id: str,
    title: str = "I Am Legend",
    year: int | None = 2007,
    duration_sec: int | None = None,
) -> sqlite3.Row | None:
    """Insert film if missing, return row."""
    cur = conn.execute("SELECT * FROM films WHERE id = ?", (film_id,))
    row = cur.fetchone()
    if row:
        return row
    fid = film_id or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO films (id, title, year, duration_sec, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (fid, title, year, duration_sec, _now(), _now()),
    )
    cur = conn.execute("SELECT * FROM films WHERE id = ?", (fid,))
    return cur.fetchone()


def upsert_asset(
    conn: sqlite3.Connection,
    film_id: str,
    kind: str,
    s3_key: str,
    bucket: str | None = None,
    s3_endpoint: str | None = None,
    datacenter: str | None = None,
    size_bytes: int | None = None,
    status: str = "available",
) -> str:
    """Insert or update asset by s3_key, return asset id."""
    cur = conn.execute("SELECT id FROM assets WHERE s3_key = ?", (s3_key,))
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE assets SET film_id=?, kind=?, bucket=?, s3_endpoint=?, datacenter=?, size_bytes=?, status=?, created_at=created_at WHERE id=?",
            (film_id, kind, bucket, s3_endpoint, datacenter, size_bytes, status, row["id"]),
        )
        return row["id"]
    aid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO assets (id, film_id, kind, s3_key, bucket, s3_endpoint, datacenter, size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, film_id, kind, s3_key, bucket, s3_endpoint, datacenter, size_bytes, status, _now()),
    )
    return aid


def insert_job(
    conn: sqlite3.Connection,
    film_id: str,
    kind: str,
    status: str = "queued",
    video_id: str | None = None,
    runpod_job_id: str | None = None,
    error: str | None = None,
) -> str:
    """Insert a new job record, return job id."""
    jid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, film_id, video_id, kind, status, runpod_job_id, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (jid, film_id, video_id, kind, status, runpod_job_id, error, _now(), _now()),
    )
    return jid


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    status: str | None = None,
    runpod_job_id: str | None = None,
    error: str | None = None,
) -> None:
    """Update job fields."""
    sets = []
    vals: list = []
    if status is not None:
        sets.append("status=?")
        vals.append(status)
    if runpod_job_id is not None:
        sets.append("runpod_job_id=?")
        vals.append(runpod_job_id)
    if error is not None:
        sets.append("error=?")
        vals.append(error)
    if not sets:
        return
    sets.append("updated_at=?")
    vals.append(_now())
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)


def get_asset_by_key(conn: sqlite3.Connection, s3_key: str) -> sqlite3.Row | None:
    """Retrieve asset by s3_key."""
    cur = conn.execute("SELECT * FROM assets WHERE s3_key=?", (s3_key,))
    return cur.fetchone()


def get_assets_for_film(conn: sqlite3.Connection, film_id: str) -> list[sqlite3.Row]:
    """Retrieve all assets for a film."""
    cur = conn.execute("SELECT * FROM assets WHERE film_id=? ORDER BY created_at", (film_id,))
    return cur.fetchall()


if __name__ == "__main__":
    conn = init_db()
    print(f"initialized {DB_PATH} exists={DB_PATH.exists()} size={DB_PATH.stat().st_size if DB_PATH.exists() else 0}")
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print("table", row[0])
