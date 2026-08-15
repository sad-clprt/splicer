"""
Film library database - indexing and discovery layer.

Provides fast search/filtering across films while detailed state
lives in per-film manifest.json files.
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


DB_PATH = Path(__file__).parent.parent / "films" / "index.db"


def get_connection() -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_connection()

    # Main films table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS films (
            film_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            year INTEGER,
            director TEXT,
            genre TEXT,
            duration_seconds INTEGER,

            -- Paths (relative to films/)
            directory_path TEXT NOT NULL,
            source_path TEXT,

            -- Status tracking
            status TEXT DEFAULT 'new',
            current_stage TEXT,

            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,

            -- Metadata
            tags TEXT,
            notes TEXT
        )
    """)

    # Indexes for common queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_title ON films(title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON films(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON films(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_director ON films(director)")

    # Full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS films_fts USING fts5(
            film_id UNINDEXED,
            title,
            director,
            tags,
            notes,
            content=films
        )
    """)

    # Triggers to keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS films_ai AFTER INSERT ON films BEGIN
            INSERT INTO films_fts(film_id, title, director, tags, notes)
            VALUES (new.film_id, new.title, new.director, new.tags, new.notes);
        END
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS films_au AFTER UPDATE ON films BEGIN
            UPDATE films_fts
            SET title = new.title, director = new.director, tags = new.tags, notes = new.notes
            WHERE film_id = new.film_id;
        END
    """)

    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS films_ad AFTER DELETE ON films BEGIN
            DELETE FROM films_fts WHERE film_id = old.film_id;
        END
    """)

    conn.commit()
    conn.close()


def add_film(
    film_id: str,
    title: str,
    directory_path: str,
    year: Optional[int] = None,
    director: Optional[str] = None,
    genre: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    source_path: Optional[str] = None,
    tags: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> None:
    """Add a new film to the index."""
    conn = get_connection()

    tags_json = json.dumps(tags) if tags else None

    conn.execute("""
        INSERT INTO films (
            film_id, title, year, director, genre, duration_seconds,
            directory_path, source_path, tags, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        film_id, title, year, director, genre, duration_seconds,
        directory_path, source_path, tags_json, notes
    ))

    conn.commit()
    conn.close()


def get_film(film_id: str) -> Optional[Dict[str, Any]]:
    """Get film by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM films WHERE film_id = ?", (film_id,)).fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def search_films(
    query: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[int] = None,
    director: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Search films with various filters.

    Args:
        query: Full-text search across title, director, tags, notes
        title: Partial title match
        year: Exact year match
        director: Partial director match
        status: Exact status match (new, in_progress, completed, failed)
        limit: Max results
    """
    conn = get_connection()

    # Full-text search takes priority
    if query:
        rows = conn.execute("""
            SELECT f.* FROM films f
            JOIN films_fts ON films_fts.film_id = f.film_id
            WHERE films_fts MATCH ?
            LIMIT ?
        """, (query, limit)).fetchall()
    else:
        # Build WHERE clause dynamically
        conditions = []
        params = []

        if title:
            conditions.append("title LIKE ?")
            params.append(f"%{title}%")

        if year:
            conditions.append("year = ?")
            params.append(year)

        if director:
            conditions.append("director LIKE ?")
            params.append(f"%{director}%")

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = conn.execute(
            f"SELECT * FROM films WHERE {where_clause} ORDER BY created_at DESC LIMIT ?",
            params
        ).fetchall()

    conn.close()
    return [dict(row) for row in rows]


def update_film_status(
    film_id: str,
    status: Optional[str] = None,
    current_stage: Optional[str] = None,
    completed_at: Optional[datetime] = None
) -> None:
    """Update film status fields."""
    conn = get_connection()

    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params = []

    if status:
        updates.append("status = ?")
        params.append(status)

    if current_stage:
        updates.append("current_stage = ?")
        params.append(current_stage)

    if completed_at:
        updates.append("completed_at = ?")
        params.append(completed_at.isoformat())

    params.append(film_id)

    conn.execute(
        f"UPDATE films SET {', '.join(updates)} WHERE film_id = ?",
        params
    )

    conn.commit()
    conn.close()


def update_film(film_id: str, **fields) -> None:
    """Update arbitrary film fields."""
    conn = get_connection()

    # Convert tags list to JSON if present
    if "tags" in fields and fields["tags"] is not None:
        fields["tags"] = json.dumps(fields["tags"])

    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params = []

    for key, value in fields.items():
        updates.append(f"{key} = ?")
        params.append(value)

    params.append(film_id)

    conn.execute(
        f"UPDATE films SET {', '.join(updates)} WHERE film_id = ?",
        params
    )

    conn.commit()
    conn.close()


def delete_film(film_id: str) -> None:
    """Remove film from index."""
    conn = get_connection()
    conn.execute("DELETE FROM films WHERE film_id = ?", (film_id,))
    conn.commit()
    conn.close()


def list_all_films(limit: int = 100) -> List[Dict[str, Any]]:
    """List all films, most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM films ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
    print(f"Database initialized at {DB_PATH}")
