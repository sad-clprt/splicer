# Splicer

**90-minute film → 14-20 minute recap pipeline**

Sequential Python pipeline using SQLite for state, RunPod Serverless for GPU work, and OpenRouter for script generation.

## Architecture

```
Local orchestrator (src/main.py)
    ↓
SQLite (src/splicer.db) — state tracking
    ↓
Pipeline stages (src/00_*.py → src/10_*.py)
    ↓
RunPod Serverless (GPU work) + OpenRouter (script gen)
    ↓
RunPod S3 Network Volume (tn1qxkkw94, EU-RO-1)
```

## Pipeline Stages

| Stage | File | Description | Location |
|---|---|---|---|
| 00 | `00_check_source.py` | Verify source 1080p exists on S3 | Local |
| 01 | `01_proxy_generate.py` | Submit 1080p → 480p transcode job | RunPod `splicer-proxy` |
| 02 | `02_proxy_download.py` | Poll proxy job, download result | RunPod → Local |
| 03 | `03_audio_enrich.py` | Submit WhisperX + scene detection | RunPod `splicer-audio-hub` |
| 04 | `04_vlm_generate.py` | Submit Qwen3-VL scene understanding | RunPod `splicer-vlm-hub` |
| 05 | `05_script_generate.py` | Generate voiceover script (gpt-4o-mini) | Local (OpenRouter) |
| 06 | `06_tts_generate.py` | Submit TTS for script | RunPod `splicer-tts-hub` |
| 07 | `07_assemble.py` | Assemble video with cuts/effects (stub) | RunPod (TODO) |
| 08 | `08_safety_run.py` | Submit Shieldstral safety check | RunPod `splicer-safety-hub` |
| 10 | `10_verify_final.py` | Verify final output quality | Local |

**Utilities:**
- `poll_job.py` — Generic RunPod job poller for stages 03/04/06/08
- `db.py` — SQLite helpers (films, assets, videos, jobs tables)
- `runpod_client.py` — RunPod SDK wrapper
- `s3.py` — S3 download/upload with 403 fallback
- `models.py` — Pydantic data models

## Setup

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Fill in:
#   RUNPOD_API_KEY
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
#   RUNPOD_ENDPOINT_* (5 endpoint IDs)
#   OPENROUTER_API_KEY

# Initialize database
uv run python -m src.db
```

## Usage

### Full Pipeline (when complete)

```bash
uv run python -m src.main \
  945c6475-a629-4140-9968-9135d716565d \
  films/945c6475-a629-4140-9968-9135d716565d/I.Am.Legend.1080p.mp4
```

### Individual Stages

```bash
# 00: Check source exists
uv run python -m src.00_check_source <film_id> <s3_key>

# 01: Submit proxy transcode
uv run python -m src.01_proxy_generate <film_id> <source_s3_key>

# 02: Poll and download proxy
uv run python -m src.02_proxy_download <film_id> <job_id>

# 03: Submit audio enrichment
uv run python -m src.03_audio_enrich <film_id> <proxy_s3_key>

# Poll audio job
uv run python -m src.poll_job <film_id> <job_id> audio audio

# 04: Submit VLM
uv run python -m src.04_vlm_generate <film_id> <proxy_s3_key> <audio_enrich_key>

# Poll VLM job
uv run python -m src.poll_job <film_id> <job_id> vlm vlm

# 05: Generate script (local)
uv run python -m src.05_script_generate <film_id> <vlm_key> <audio_enrich_key>

# 06: Submit TTS
uv run python -m src.06_tts_generate <film_id> <script_text>

# Poll TTS job
uv run python -m src.poll_job <film_id> <job_id> tts tts

# 08: Submit safety check
uv run python -m src.08_safety_run <film_id> <final_s3_key>

# Poll safety job
uv run python -m src.poll_job <film_id> <job_id> safety safety

# 10: Verify final
uv run python -m src.10_verify_final <film_id> <final_path>
```

## Database Schema

```sql
-- Films metadata
films(id, title, year, duration_sec, ...)

-- S3 assets (source, proxy, audio, vlm, script, tts, final)
assets(id, film_id, kind, s3_key, bucket, size_bytes, status, ...)

-- Video outputs
videos(id, film_id, final_asset_id, status, script, script_hash, ...)

-- RunPod job tracking
jobs(id, film_id, video_id, kind, status, runpod_job_id, error, ...)
```

## RunPod Endpoints

| Name | ID (example) | Image | Purpose |
|---|---|---|---|
| splicer-proxy | `2dmz605z5wxjo1` | custom | ffmpeg h264_nvenc transcode |
| splicer-audio-hub | `0jj6liixhjnhbh` | Hub: hapnan-whisperx | WhisperX + scene detect |
| splicer-vlm-hub | `i5xjuwuikr335p` | Hub: worker-vllm (Qwen3-VL) | Frame → scene descriptions |
| splicer-tts-hub | `5fb99jvt01k63a` | Hub: chatterbox | Script → audio |
| splicer-safety-hub | `yams2crmm7o6l9` | Hub: worker-vllm (Shieldstral) | Content moderation |

**Note:** Proxy endpoint needs cloud-built image (GitHub or Hub) — volume handlers don't execute on generic `runpod/base`.

## Development

```bash
# Lint
uv run ruff check src/

# Format
uv run ruff format src/

# Type check
uv run ty src/

# Test
uv run pytest
```

## Migration from Old Structure

This replaces:
- ~~`app/` (FastAPI modules)~~ → `src/` numbered stages
- ~~`scripts/` (mixed pipeline)~~ → `src/` numbered stages
- ~~FastAPI + Inngest orchestration~~ → `src/main.py` sequential
- ~~Neon Postgres~~ → SQLite `src/splicer.db`
- ~~OpenAI SDK~~ → OpenRouter direct
- ~~Logfire~~ → loguru + rich

Old code preserved in `app/` and `scripts/` until new structure verified.

## TODO

- [ ] Complete `07_assemble.py` with moviepy video editing
- [ ] Add moviepy to dependencies
- [ ] Integrate all stages into `main.py` orchestrator
- [ ] Add progress bars and rich formatting to main.py
- [ ] Write tests for each stage
- [ ] Deploy proxy handler to RunPod (cloud build or Hub)
- [ ] Verify full pipeline on canary film
- [ ] Archive old `app/` and `scripts/` directories
