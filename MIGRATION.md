# Splicer Architecture Migration — Complete

## Summary

Successfully migrated splicer from FastAPI + Inngest + Neon to a simplified local-first pipeline:

**Before:**
- `app/` — FastAPI modules with SQLAlchemy ORM
- `scripts/` — Mixed pipeline scripts
- FastAPI + Inngest orchestration
- Neon Postgres database
- Complex async/event-driven architecture

**After:**
- `src/` — Flat, numbered pipeline stages (stage_00 → stage_10)
- Sequential execution via `src/main.py`
- SQLite database (`src/splicer.db`)
- Simple, synchronous orchestration
- Rich terminal UI with progress indicators

## New Structure

```
src/
├── __init__.py
├── stage_00_check_source.py      # Verify source 1080p exists
├── stage_01_proxy_generate.py    # Submit 480p transcode job
├── stage_02_proxy_download.py    # Poll and download proxy
├── stage_03_audio_enrich.py      # Submit WhisperX job
├── stage_04_vlm_generate.py      # Submit Qwen3-VL job
├── stage_05_script_generate.py   # Generate script (OpenRouter)
├── stage_06_tts_generate.py      # Submit TTS job
├── stage_07_assemble.py          # Assemble video (stub)
├── stage_08_safety_run.py        # Submit safety check
├── stage_10_verify_final.py      # Verify final output
├── poll_job.py                   # Generic job poller
├── db.py                          # SQLite helpers
├── runpod_client.py              # RunPod SDK wrapper
├── s3.py                          # S3 helpers
├── models.py                      # Pydantic models
└── main.py                        # Orchestrator
```

## Dependencies Changed

### Removed:
- `alembic` — no migrations needed for SQLite
- `fastapi[standard]` — no API server
- `inngest` — no event orchestration
- `logfire[fastapi]` — no observability platform
- `psycopg[binary]` — no Postgres
- `sqlalchemy` — raw SQLite instead
- `upstash-redis` — no Redis
- `uvicorn[standard]` — no ASGI server
- `openai` — replaced by openrouter

### Added:
- `runpod` — RunPod Python SDK
- `openrouter` — OpenRouter API client
- `rich` — Terminal UI

### Kept:
- `boto3` — S3 operations
- `loguru` — Logging
- `pydantic` — Data validation
- `python-dotenv` — Environment variables
- `requests` — HTTP requests

## Database Schema

SQLite `src/splicer.db` with 4 tables:

1. **films** — Film metadata (id, title, year, duration)
2. **assets** — S3 pointers (source, proxy, audio, vlm, script, tts, final)
3. **videos** — Output videos (script, script_hash, status)
4. **jobs** — RunPod job mirror (kind, status, runpod_job_id, error)

## Usage

```bash
# Full pipeline (when complete)
uv run python -m src.main <film_id> <source_s3_key>

# Individual stages
uv run python -m src.stage_00_check_source <film_id> <s3_key>
uv run python -m src.stage_01_proxy_generate <film_id> <source_s3_key>
uv run python -m src.stage_02_proxy_download <film_id> <job_id>
# ... etc
```

## What's Left

1. **Complete stage_07_assemble.py** — moviepy video editing logic
2. **Add moviepy to dependencies** — video editing library
3. **Integrate all stages into main.py** — full orchestrator
4. **Write tests** — pytest for each stage
5. **Deploy proxy handler** — cloud build or Hub
6. **Verify full pipeline** — run on canary film
7. **Archive old code** — remove `app/` and `scripts/` directories

## Testing

```bash
# Initialize database
uv run python -m src.db
# Output: initialized /home/samir/Projects/splicer/src/splicer.db

# Test imports
uv run python -c "import src.stage_00_check_source; print('OK')"

# Lint
uv run ruff check src/

# Format
uv run ruff format src/
```

## Migration Notes

- Old `app/` and `scripts/` directories preserved until new structure verified
- `.env` structure unchanged (same keys, removed DATABASE_URL)
- RunPod endpoints unchanged (same IDs)
- S3 bucket/volume unchanged (tn1qxkkw94)
- Git: commit needed after verification

## Verification Checklist

- [x] Dependencies updated (`pyproject.toml`)
- [x] SQLite database schema created (`src/splicer.db`)
- [x] All 10 pipeline stages created
- [x] Utilities migrated (db, s3, runpod_client)
- [x] Models defined (Pydantic)
- [x] Main orchestrator created
- [x] Generic job poller created
- [x] README updated
- [x] .env.example created
- [x] Imports tested
- [x] Linter run (3 minor warnings remain)
- [ ] Full pipeline test (requires endpoints configured)
- [ ] Tests written
- [ ] Old code archived

## Next Steps

1. Configure `.env` with actual RunPod endpoint IDs
2. Test stage_00 and stage_01 with real film
3. Complete stage_07_assemble with moviepy
4. Write pytest tests for each stage
5. Run full pipeline on canary film
6. Archive `app/` and `scripts/` directories
7. Update HANDOFF.md with new structure
