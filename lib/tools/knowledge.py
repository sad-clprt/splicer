"""
Knowledge enrichment tool - External API lookups for film context.

Fetches cast, plot, themes, trivia from external sources (TMDB, OMDB, etc.)
"""

from pathlib import Path
from typing import Optional, Dict, Any, List

from ..film_manager import get_film_dir, get_manifest, update_stage_status


def enrich_knowledge(
    film_id: str,
    sources: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Enrich film with external knowledge sources.

    Args:
        film_id: Film identifier
        sources: List of sources to query (e.g., ["tmdb", "omdb", "wikipedia"])

    Returns:
        Enrichment data dict with cast, plot, themes, trivia

    TODO:
        - Query TMDB API for cast, crew, plot
        - Query OMDB for ratings, awards
        - Optional: Wikipedia for plot summary
        - Save to knowledge/context.json
        - Update manifest
    """
    manifest = get_manifest(film_id)
    title = manifest.get("title")
    year = manifest.get("year")

    if not title:
        raise ValueError(f"Film title not found in manifest: {film_id}")

    update_stage_status(
        film_id=film_id,
        stage="knowledge",
        status="in_progress",
        details={"sources": sources or ["tmdb"], "message": "TODO: API integration pending"}
    )

    # TODO: Implement external API queries
    # 1. Query TMDB: /search/movie?query={title}&year={year}
    # 2. Get movie details: /movie/{id}?append_to_response=credits,keywords
    # 3. Query OMDB if needed
    # 4. Combine data

    knowledge_data = {
        "title": title,
        "year": year,
        "cast": [],  # TODO: Fetch from TMDB
        "crew": {},  # TODO: Fetch from TMDB
        "plot": "",  # TODO: Fetch from TMDB/OMDB
        "themes": [],  # TODO: Extract from keywords
        "trivia": [],  # TODO: Optional
        "sources": sources or ["tmdb"],
        "status": "TODO",
        "message": "Knowledge enrichment not implemented"
    }

    context_path = get_film_dir(film_id) / "knowledge" / "context.json"

    # TODO: Save knowledge_data to context_path

    update_stage_status(
        film_id=film_id,
        stage="knowledge",
        status="completed",
        details={"context_path": "knowledge/context.json"}
    )

    return knowledge_data


def get_cast(film_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """
    Get cast list from saved knowledge.

    Args:
        film_id: Film identifier
        limit: Max number of cast members

    Returns:
        List of cast dicts with name, character, profile_url

    TODO:
        - Load from knowledge/context.json
        - Return cast list
    """
    context_path = get_film_dir(film_id) / "knowledge" / "context.json"

    if not context_path.exists():
        raise FileNotFoundError(f"Knowledge context not found: {context_path}")

    # TODO: Load and parse context.json
    # return knowledge_data["cast"][:limit]

    return []


def get_plot_summary(film_id: str) -> str:
    """
    Get plot summary from saved knowledge.

    Args:
        film_id: Film identifier

    Returns:
        Plot summary text

    TODO:
        - Load from knowledge/context.json
        - Return plot summary
    """
    context_path = get_film_dir(film_id) / "knowledge" / "context.json"

    if not context_path.exists():
        raise FileNotFoundError(f"Knowledge context not found: {context_path}")

    # TODO: Load and parse context.json
    # return knowledge_data["plot"]

    return "TODO: Plot summary not implemented"


def get_themes(film_id: str) -> List[str]:
    """
    Get film themes from saved knowledge.

    Args:
        film_id: Film identifier

    Returns:
        List of theme strings

    TODO:
        - Load from knowledge/context.json
        - Return themes list
    """
    context_path = get_film_dir(film_id) / "knowledge" / "context.json"

    if not context_path.exists():
        raise FileNotFoundError(f"Knowledge context not found: {context_path}")

    # TODO: Load and parse context.json
    # return knowledge_data["themes"]

    return []
