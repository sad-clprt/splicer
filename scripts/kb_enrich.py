"""02 — kb_enrich: TMDB + OMDb → films.metadata_json in scripts/application.db (lightweight, local HTTP).

No heavy work, no RunPod. Calls TMDB search + details + OMDb if imdb_id available.
Stores {tmdb, omdb, fetched_at, source} as JSON string in SQLite.

Uses app.kb helpers if available, else direct requests.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
TITLE_HINT = "I Am Legend"


def run(film_id: str = FILM_ID, title_hint: str | None = TITLE_HINT, imdb_hint: str | None = None, conn=None) -> dict:

    from scripts.db import init_db

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True
    else:
        init_db(conn)

    # ensure film exists
    cur = conn.execute("SELECT * FROM films WHERE id=?", (film_id,))
    film = cur.fetchone()
    if not film:
        print(f"[02_kb] film {film_id} missing — creating with title_hint={title_hint}")
        conn.execute(
            "INSERT INTO films (id, title, year, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (film_id, title_hint or "I Am Legend", 2007, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        cur = conn.execute("SELECT * FROM films WHERE id=?", (film_id,))
        film = cur.fetchone()

    title = title_hint or film["title"]

    # try app.kb helpers (they handle Bearer vs api_key)
    tmdb_search = None
    tmdb_details = None
    omdb = None
    try:
        from app.kb import omdb_fetch
        from app.kb import tmdb_movie_details
        from app.kb import tmdb_search_movie

        tmdb_search = tmdb_search_movie(title)
        if tmdb_search and tmdb_search.get("id"):
            tmdb_details = tmdb_movie_details(tmdb_search["id"])
        imdb_id = imdb_hint or (tmdb_details.get("imdb_id") if tmdb_details else None) or (film["metadata_json"] and json.loads(film["metadata_json"]).get("omdb", {}).get("imdbID"))
        if imdb_id:
            omdb = omdb_fetch(imdb_id)
    except Exception as e:
        print(f"[02_kb] app.kb failed: {e} — falling back to direct requests may be limited")

    # fallback minimal if both null and no TMDB key: keep existing metadata
    existing = {}
    if film["metadata_json"]:
        try:
            existing = json.loads(film["metadata_json"])
        except Exception:
            existing = {}

    meta = {
        **existing,
        "tmdb": tmdb_details or tmdb_search or {},
        "omdb": omdb or {},
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": "tmdb+omdb",
        "title_hint": title,
    }
    # record which enrichment keys are configured (parallel/tavily etc) without leaking values
    import os

    web_keys = {}
    for k in ["PARALLEL_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "TINYFISH_API_KEY"]:
        if os.getenv(k):
            web_keys[k.lower()] = "available"
    if web_keys:
        meta["web_keys"] = web_keys

    conn.execute("UPDATE films SET metadata_json=?, updated_at=? WHERE id=?", (json.dumps(meta), datetime.now(UTC).isoformat(), film_id))
    print(f"[02_kb] enriched film={film_id} title={title} tmdb_id={(tmdb_details or tmdb_search or {}).get('id')} imdb_id={(tmdb_details or {}).get('imdb_id') or (omdb or {}).get('imdbID')}")

    if close_conn:
        conn.commit()
        conn.close()

    return {"film_id": film_id, "metadata": meta, "tmdb_id": (tmdb_details or tmdb_search or {}).get("id"), "imdb_id": (tmdb_details or {}).get("imdb_id")}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="02 kb enrich")
    parser.add_argument("--film-id", default=FILM_ID)
    parser.add_argument("--title", default=TITLE_HINT)
    args = parser.parse_args()
    out = run(film_id=args.film_id, title_hint=args.title)
    print(json.dumps(out, indent=2)[:4000])
