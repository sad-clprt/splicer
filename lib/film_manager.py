"""
Film manager - handles film lifecycle and manifest operations.

Each film has:
- Directory: films/{film_id}/
- Manifest: films/{film_id}/manifest.json
- Index entry: films/index.db
"""

import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from . import db


FILMS_DIR = Path(__file__).parent.parent / "films"


def generate_film_id(title: str, year: Optional[int] = None) -> str:
    """
    Generate film ID from title and year.

    Examples:
        "Inception", 2010 -> "inception_2010"
        "The Matrix" -> "the_matrix_{uuid4}"
    """
    # Slugify title
    slug = title.lower()
    slug = "".join(c if c.isalnum() or c.isspace() else "" for c in slug)
    slug = "_".join(slug.split())

    if year:
        return f"{slug}_{year}"
    else:
        # No year provided, use short UUID suffix
        short_uuid = str(uuid.uuid4())[:8]
        return f"{slug}_{short_uuid}"


def create_film(
    title: str,
    source_path: Optional[Path] = None,
    year: Optional[int] = None,
    director: Optional[str] = None,
    genre: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    tags: Optional[List[str]] = None,
    notes: Optional[str] = None,
    film_id: Optional[str] = None,
) -> str:
    """
    Create a new film entry with directory structure and manifest.

    Args:
        title: Film title
        source_path: Optional path to source video (will be copied)
        year: Release year
        director: Director name
        genre: Genre/category
        duration_seconds: Duration in seconds
        tags: List of tags for searching
        notes: User notes
        film_id: Optional custom film_id (generated if not provided)

    Returns:
        film_id
    """
    # Generate film_id if not provided
    if not film_id:
        film_id = generate_film_id(title, year)

    # Create directory structure
    film_dir = FILMS_DIR / film_id
    if film_dir.exists():
        raise ValueError(f"Film directory already exists: {film_id}")

    film_dir.mkdir(parents=True)
    (film_dir / "audio").mkdir()
    (film_dir / "visual").mkdir()
    (film_dir / "knowledge").mkdir()
    (film_dir / "script").mkdir()
    (film_dir / "voiceover").mkdir()
    (film_dir / "voiceover" / "segments").mkdir()
    (film_dir / "output").mkdir()
    (film_dir / "output" / "versions").mkdir()

    # Copy source video if provided
    source_filename = None
    if source_path and source_path.exists():
        source_filename = f"source{source_path.suffix}"
        dest = film_dir / source_filename
        shutil.copy2(source_path, dest)

    # Create manifest
    manifest = {
        "film_id": film_id,
        "title": title,
        "year": year,
        "director": director,
        "genre": genre,
        "duration_seconds": duration_seconds,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "status": {
            "proxy": {"status": "not_started"},
            "audio": {"status": "not_started"},
            "knowledge": {"status": "not_started"},
            "visual": {"status": "not_started"},
            "script": {"status": "not_started", "version": 0},
            "voiceover": {"status": "not_started"},
            "assembly": {"status": "not_started"},
            "safety": {"status": "not_started"},
        },
        "history": [
            {
                "action": "created",
                "timestamp": datetime.now().isoformat(),
                "details": {"title": title, "source": str(source_path) if source_path else None}
            }
        ],
        "files": {
            "source": source_filename,
            "proxy": None,
        },
        "tags": tags or [],
        "notes": notes,
    }

    manifest_path = film_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # Add to database index
    db.add_film(
        film_id=film_id,
        title=title,
        year=year,
        director=director,
        genre=genre,
        duration_seconds=duration_seconds,
        directory_path=f"{film_id}/",
        source_path=f"{film_id}/{source_filename}" if source_filename else None,
        tags=tags,
        notes=notes,
    )

    return film_id


def get_film_dir(film_id: str) -> Path:
    """Get film directory path."""
    return FILMS_DIR / film_id


def get_manifest(film_id: str) -> Dict[str, Any]:
    """Load film manifest."""
    manifest_path = get_film_dir(film_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found for film: {film_id}")

    return json.loads(manifest_path.read_text())


def update_manifest(film_id: str, updates: Dict[str, Any]) -> None:
    """Update film manifest with partial updates."""
    manifest = get_manifest(film_id)

    # Merge updates
    manifest.update(updates)
    manifest["updated_at"] = datetime.now().isoformat()

    # Write back
    manifest_path = get_film_dir(film_id) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))


def update_stage_status(
    film_id: str,
    stage: str,
    status: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """
    Update status of a specific stage.

    Args:
        film_id: Film identifier
        stage: Stage name (proxy, audio, knowledge, visual, script, voiceover, assembly, safety)
        status: Status value (not_started, in_progress, completed, failed)
        details: Additional details to store in status
    """
    manifest = get_manifest(film_id)

    stage_status = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }

    if details:
        stage_status.update(details)

    manifest["status"][stage] = stage_status
    manifest["updated_at"] = datetime.now().isoformat()

    # Add to history
    manifest["history"].append({
        "action": f"{stage}_{status}",
        "timestamp": datetime.now().isoformat(),
        "details": details or {}
    })

    # Write back
    manifest_path = get_film_dir(film_id) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # Update database index
    overall_status = "in_progress"
    if all(s["status"] == "completed" for s in manifest["status"].values()):
        overall_status = "completed"
    elif any(s["status"] == "failed" for s in manifest["status"].values()):
        overall_status = "failed"
    elif all(s["status"] == "not_started" for s in manifest["status"].values()):
        overall_status = "new"

    db.update_film_status(
        film_id=film_id,
        status=overall_status,
        current_stage=stage
    )


def add_history_entry(film_id: str, action: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Add entry to film history log."""
    manifest = get_manifest(film_id)

    manifest["history"].append({
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "details": details or {}
    })

    manifest_path = get_film_dir(film_id) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))


def delete_film(film_id: str, remove_files: bool = False) -> None:
    """
    Delete film from index and optionally remove files.

    Args:
        film_id: Film identifier
        remove_files: If True, deletes the entire film directory
    """
    # Remove from database
    db.delete_film(film_id)

    # Remove files if requested
    if remove_files:
        film_dir = get_film_dir(film_id)
        if film_dir.exists():
            shutil.rmtree(film_dir)


def list_films(**filters) -> List[Dict[str, Any]]:
    """
    List films with optional filters.

    Passes filters through to db.search_films().
    Returns combined data from index + manifest status.
    """
    return db.search_films(**filters)


def get_film_info(film_id: str) -> Dict[str, Any]:
    """
    Get complete film info (index + manifest).

    Returns:
        Combined dict with index metadata + manifest details
    """
    # Get from index
    index_data = db.get_film(film_id)
    if not index_data:
        raise ValueError(f"Film not found in index: {film_id}")

    # Get manifest
    try:
        manifest = get_manifest(film_id)
        index_data["manifest"] = manifest
    except FileNotFoundError:
        index_data["manifest"] = None

    return index_data
