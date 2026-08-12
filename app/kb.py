"""Knowledge base enrichment — TMDB + OMDb + web search → films.metadata JSONB.

- TMDB: GET /3/search/movie?query= -> 6479, then /3/movie/6479?append_to_response=credits
- OMDb: ?i=tt0480249&plot=full (via imdb_id)
- Web: parallel/tinyfish via global .env keys (optional)
Stored as films.metadata with {tmdb, omdb, web, fetched_at}.
"""

import datetime
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


def _tmdb_headers() -> dict[str, str]:
    token = (
        os.getenv("TMDB_API_READ_TOKEN")
        or os.getenv("TMDB_API_KEY")
        or os.getenv("TMDB_BEARER")
        or ""
    )
    # HANDOFF notes: TMDB Bearer eyJ... and f0ad4...
    if token.startswith("eyJ"):
        return {"Authorization": f"Bearer {token}"}
    # if plain api key, use query param instead
    return {}


def tmdb_search_movie(title: str) -> dict[str, Any] | None:
    base = "https://api.themoviedb.org/3/search/movie"
    token = os.getenv("TMDB_API_READ_TOKEN") or os.getenv("TMDB_API_KEY")
    headers = _tmdb_headers()
    params = {"query": title}
    if token and not token.startswith("eyJ"):
        params["api_key"] = token
    try:
        r = requests.get(base, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()
        results = j.get("results", [])
        if not results:
            return None
        # pick first result matching title approx
        return results[0]
    except Exception:
        return None


def tmdb_movie_details(tmdb_id: int | str) -> dict[str, Any] | None:
    base = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    token = os.getenv("TMDB_API_READ_TOKEN") or os.getenv("TMDB_API_KEY")
    headers = _tmdb_headers()
    params = {"append_to_response": "credits"}
    if token and not token.startswith("eyJ"):
        params["api_key"] = token
    try:
        r = requests.get(base, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def omdb_fetch(imdb_id: str) -> dict[str, Any] | None:
    key = os.getenv("OMDB_API_KEY")
    if not key or not imdb_id:
        return None
    try:
        r = requests.get(
            "http://www.omdbapi.com/",
            params={"i": imdb_id, "apikey": key, "plot": "full"},
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("Response") == "False":
            return None
        return j
    except Exception:
        return None


def enrich_film_metadata(
    film_id: str, title_hint: str | None = None, imdb_hint: str | None = None
) -> dict[str, Any]:
    from app.database import SessionLocal
    from app.models import Film

    db = SessionLocal()
    try:
        film = db.query(Film).filter(Film.id == film_id).first()
        if not film:
            raise ValueError(f"film {film_id} not found")
        title = title_hint or film.title
        # TMDB
        search = tmdb_search_movie(title)
        details = None
        if search:
            tmdb_id = search.get("id")
            film.tmdb_id = str(tmdb_id) if tmdb_id else film.tmdb_id  # type: ignore
            details = tmdb_movie_details(tmdb_id)
            if details and details.get("imdb_id"):
                film.imdb_id = details.get("imdb_id")  # type: ignore
        # OMDb using imdb_id
        imdb_id = imdb_hint or film.imdb_id or (details.get("imdb_id") if details else None)
        omdb = omdb_fetch(imdb_id) if imdb_id else None
        if omdb and omdb.get("imdbID"):
            film.imdb_id = omdb.get("imdbID")  # type: ignore
        # build metadata
        existing = film.metadata_json or {}
        meta = {
            **existing,
            "tmdb": details or search or {},
            "omdb": omdb or {},
            "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": "tmdb+omdb",
        }
        # web enrichment placeholder — parallel/tinyfish keys if set
        # keep lightweight; actual web calls done via separate parallel search if keys present
        web = {}
        for k in ["PARALLEL_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "TINYFISH_API_KEY"]:
            if os.getenv(k):
                web[k.lower()] = "available"
        if web:
            meta["web_keys"] = web
        film.metadata_json = meta  # type: ignore
        db.commit()
        db.refresh(film)
        return {
            "film_id": str(film.id),
            "tmdb_id": film.tmdb_id,
            "imdb_id": film.imdb_id,
            "metadata": meta,
        }
    finally:
        db.close()
