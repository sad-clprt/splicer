"""Stage 02.5: Knowledge Base Enrichment (TMDB + OMDB metadata).

Fetches comprehensive film metadata from TMDB and OMDB APIs to enrich the pipeline
context. This gives script generation and editing stages rich contextual information:
- Plot synopsis, themes, character names
- Genre, ratings, reviews
- Director, cast, release info
- Keywords, similar films

Output: films/<film_id>/kb_enrich.json uploaded to S3
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import requests
from loguru import logger
from rich.console import Console

from . import db, s3

console = Console()


def fetch_tmdb_data(title: str, year: int | None = None) -> dict | None:
    """Fetch movie data from TMDB API.

    Args:
        title: Film title
        year: Release year (optional, helps with disambiguation)

    Returns:
        TMDB movie data dict or None
    """
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        logger.warning("TMDB_API_KEY not set, skipping TMDB enrichment")
        return None

    try:
        # Search for movie
        search_url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": api_key, "query": title}
        if year:
            params["year"] = year

        resp = requests.get(search_url, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            logger.warning(f"No TMDB results for '{title}' ({year})")
            return None

        # Get first result details
        movie_id = results[0]["id"]
        details_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        params = {
            "api_key": api_key,
            "append_to_response": "credits,keywords,reviews,similar",
        }

        resp = requests.get(details_url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        logger.exception(f"TMDB fetch failed: {e}")
        return None


def fetch_omdb_data(title: str, year: int | None = None) -> dict | None:
    """Fetch movie data from OMDB API.

    Args:
        title: Film title
        year: Release year (optional)

    Returns:
        OMDB movie data dict or None
    """
    api_key = os.getenv("OMDB_API_KEY")
    if not api_key:
        logger.warning("OMDB_API_KEY not set, skipping OMDB enrichment")
        return None

    try:
        url = "http://www.omdbapi.com/"
        params = {"apikey": api_key, "t": title, "plot": "full"}
        if year:
            params["y"] = year

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("Response") == "False":
            logger.warning(f"OMDB error: {data.get('Error')}")
            return None

        return data

    except Exception as e:
        logger.exception(f"OMDB fetch failed: {e}")
        return None


def kb_enrich(film_id: str, title: str = "I Am Legend", year: int | None = 2007) -> str | None:
    """Enrich knowledge base with TMDB and OMDB metadata.

    Args:
        film_id: unique film identifier
        title: film title for API queries
        year: release year (helps with disambiguation)

    Returns:
        S3 key for kb_enrich.json if successful, None otherwise
    """
    logger.info(f"[02.5_kb_enrich] Enriching KB for '{title}' ({year})")

    try:
        # Fetch from both APIs
        tmdb_data = fetch_tmdb_data(title, year)
        omdb_data = fetch_omdb_data(title, year)

        if not tmdb_data and not omdb_data:
            logger.error("Both TMDB and OMDB failed, no enrichment data")
            return None

        # Combine data
        enrichment = {
            "film_id": film_id,
            "title": title,
            "year": year,
            "tmdb": tmdb_data,
            "omdb": omdb_data,
        }

        # Extract key fields for easy access
        summary = {
            "plot": omdb_data.get("Plot") if omdb_data else tmdb_data.get("overview"),
            "genres": [g["name"] for g in tmdb_data.get("genres", [])] if tmdb_data else omdb_data.get("Genre", "").split(", ") if omdb_data else [],
            "director": omdb_data.get("Director") if omdb_data else None,
            "cast": omdb_data.get("Actors", "").split(", ") if omdb_data else [c["name"] for c in tmdb_data.get("credits", {}).get("cast", [])[:10]] if tmdb_data else [],
            "keywords": [k["name"] for k in tmdb_data.get("keywords", {}).get("keywords", [])] if tmdb_data else [],
            "rating_imdb": omdb_data.get("imdbRating") if omdb_data else None,
            "rating_tmdb": tmdb_data.get("vote_average") if tmdb_data else None,
            "runtime_min": int(omdb_data.get("Runtime", "0").split()[0]) if omdb_data and omdb_data.get("Runtime") else tmdb_data.get("runtime") if tmdb_data else None,
        }
        enrichment["summary"] = summary

        # Upload to S3
        kb_key = f"films/{film_id}/kb_enrich.json"
        kb_tmp = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".json")
        json.dump(enrichment, kb_tmp, indent=2)
        kb_tmp.close()

        s3_client = s3.get_s3_client()
        s3_client.upload_file(kb_tmp.name, s3.VOLUME_ID, kb_key)
        Path(kb_tmp.name).unlink()

        logger.info(f"KB enrichment uploaded: {kb_key}")

        # Register in DB - ensure film exists first
        conn = db.init_db()
        db.ensure_film(conn, film_id=film_id, title=title, year=year, duration_sec=summary["runtime_min"] * 60 if summary["runtime_min"] else None)
        db.upsert_asset(
            conn,
            film_id=film_id,
            kind="kb_enrich",
            s3_key=kb_key,
            bucket=s3.VOLUME_ID,
            size_bytes=len(json.dumps(enrichment)),
            status="available",
        )
        conn.close()

        console.print(f"[green]✓[/green] KB enriched: {kb_key}")
        console.print(f"  Plot: {summary['plot'][:100]}...")
        console.print(f"  Genres: {', '.join(summary['genres'][:3])}")
        console.print(f"  Cast: {', '.join(summary['cast'][:3])}")

        return kb_key

    except Exception as e:
        logger.exception(f"kb_enrich failed: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.stage_02_5_kb_enrich <film_id> [title] [year]")
        sys.exit(1)

    film_id = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "I Am Legend"
    year = int(sys.argv[3]) if len(sys.argv) > 3 else 2007

    kb_key = kb_enrich(film_id, title, year)
    sys.exit(0 if kb_key else 1)
