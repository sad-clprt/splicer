# HANDOFF — Splicer Movie Recap Pipeline

**One-line:** 90 min film + subs + metadata → 12-14 min (now 14-20) voiceover-only YouTube recap, no original audio/music, 1080p final + 480p proxy for local Blender. Fully automated via FastAPI service, RunPod GPUs, hierarchical VLM.

---

## 1. Stack & Resources

| Area | Choice | Notes |
|---|---|---|
| **API** | FastAPI `[standard]` + Pydantic validation, `/docs` only (no frontend) | `main.py` app, lifespan, health checks |
| **Orchestration** | Inngest (durable, `concurrency=3` dev, env-tunable to 30) | `splicer` app_id, `INNGEST_DEV=1` dummy `signkey-test-fake`, 2 fns: `hello_pipeline`, `proxy_film` |
| **Observability** | Pydantic Logfire `logfire[fastapi]==4.40.0`, `instrument_fastapi/pydantic/sqlalchemy` | `LOGFIRE_TOKEN=pylf_v2_us_...` injected via FastAPI Cloud, else console |
| **DB** | Neon Postgres PG18 `wispy-meadow-57216942` `aws-us-east-2` (pooled for app, direct for Alembic) | `DATABASE_URL` pooled `-pooler`, Alembic strips `-pooler` + `+psycopg` for psycopg3 |
| **ORM/Migrations** | SQLAlchemy 2.0 + Alembic (not SQLModel) | `app/database.py` `psycopg[binary]`, `app/models.py` |
| **Deploy** | FastAPI Cloud (`fastapi deploy`, auto-injects `DATABASE_URL` + `LOGFIRE_TOKEN`) | `fastapi-cloud-cli 0.23.0` |
| **Compute** | RunPod: Serverless queue-based (proxy/VLM/TTS) + Pods for one-off transcode | `runpodctl 2.6.0`, `hf 1.27.0` |
| **Storage** | RunPod Network Volume `tn1qxkkw94` `splicer-films` 50GB `STANDARD` `EU-RO-1` → S3 API `https://s3api-eu-ro-1.runpod.io` bucket=volume_id | `200-400 MB/s`, `s3://<VOL>/films/<id>/...` |
| **Video** | PyNvVideoCodec (NVDEC/NVENC) + FFmpeg, `transcode 1072 FPS` vs FFmpeg 389 FPS (L40G), GOP30 best | For proxy + final export |
| **Scene** | PySceneDetect `ContentDetector/AdaptiveDetector` | Boundaries → 1 FPS sampling |
| **VLM** | Qwen3-VL-8B-Instruct via vLLM (128-256 tokens/frame ≈362×362/512×512, patch16 merge2 32×, no tiling, 8-frame batches, `max_num_seqs 64`) | Hierarchical: 5400 frames → 675×8-frame clips → text aggregate |
| **TTS** | Qwen3-TTS-12Hz-1.7B-CustomVoice | After script final |
| **Safety** | Shieldstral-1.0-3B (Ministral-3B+Pixtral, policy-adaptive, single forward pass) | **Only on final 14-20 min recap** (~840-1200 frames), not full 90 min |
| **Script** | OpenRouter (unified 400+ models, Python SDK) + stronger LLM for final script | Qwen-VL only for visual grounding |
| **Enrichment** | TMDB (`f0ad4…` Bearer `eyJ...`), OMDb (`85175a64`), Parallel/TinyFish/Exa/Tavily (global `.env` `fbJu…`, `sk-tinyfish…`, `27c1…`, `tvly…`) | Natural questions: `What is I Am Legend about?`, cast, characters |
| **Editing** | Blender Python | markers for scenes/safety |
| **Other** | Verda CPU researched (CPU.4V $0.0279/h vs RunPod cpu3g 4×$0.04=$0.16/h, but GPU 4090 $0.34/h wins for transcode), Neon's pooled vs direct, `codegraph` indexed | |

---

## 2. MCPs (project-local only, `splicer/.pi/mcp.json` — global `~/.pi/agent/mcp.json` untouched)

```
runpod        npx -y @runpod/mcp-server@latest  env RUNPOD_API_KEY=rpa_80K... (hardcoded)
runpod-docs   https://docs.runpod.io/mcp (4 tools)
inngest       http://127.0.0.1:8288/mcp (lazy, needs `inngest dev -u http://localhost:8000/api/inngest`)
neon          https://mcp.neon.tech/mcp  Authorization Bearer napi_... (hardcoded placeholder → real)
logfire       https://logfire-us.pydantic.dev/mcp  Bearer pylf_v2_us_e5db... (hardcoded)
deepwiki/codegraph  global only
```

All verified: `runpod 54`, `runpod-docs 4`, `neon 34`, `logfire 75` tools. `inngest` ECONNREFUSED until dev server up. Restart Pi after editing `.pi/mcp.json` to load. `.pi/mcp.json` **not gitignored** — contains real `rpa_...` (rotate if committed).

---

## 3. Architecture

```
Client (curl, 3 parallel) → FastAPI Cloud
  ├─ POST /api/uploads/init → mint presigned multipart (CreateMultipartUpload + presigned upload_part URLs, concurrency 3)
  │   └─ Neon assets(status=uploading, codec=UploadId)
  ├─ PUT direct to S3 s3://tn1qxkkw94/... (bypass FastAPI) OR POST /api/uploads?kind=source_1080p|subtitle (direct streaming via boto3, fallback for presigned 401)
  └─ POST /api/uploads/{id}/complete → ListParts/Complete, HeadObject(403 fallback to List), assets→available, Inngest send film/proxy.requested
        └─ Inngest (3 concurrent) → RunPod GPU ADA_24 (RTX 4090 2 NVDEC, GOP30, cached decoder 7.2× short clips, segmented 2.8×) → 480p proxy on volume → S3 list verifies

Neon: films → assets (s3_key, volume_id, endpoint, datacenter) → videos (720-840s target, script) → jobs (Inngest mirror)
  └─ Add TMDB/OMDb + Parallel search → films.metadata JSONB

Full pipeline (Grok hierarchical, 5400 frames not 129k):
  90m 24FPS → PySceneDetect + SRT → 1 FPS uniform (NVDEC 2 threads 4090, GOP30) → 5400 frames (device-mem resize 362×362, 128 tokens) → chunk 8-frame clips (675) → Qwen3-VL Stage1 JSON (chars/actions/importance) → Stage2 fuse per scene (visual + sub + diarization + KB) → Stage3 act/beat outline → OpenRouter stronger model → script → Qwen-TTS → Blender/NVENC → Shieldstral on final only
```

Blobs never in Postgres — only pointers. Subtitles SRT primary, WhisperX only gaps. `librosa` energy + `pyannote` diarization optional.

---

## 4. DB Schema (`alembic 0f1518859de0`)

```sql
films(id UUID PK, title, year, director, cast JSONB, tmdb_id UQ, imdb_id UQ, duration_sec, metadata JSONB, created_at)
assets(id UUID PK, film_id FK, kind ENUM source_1080p/proxy_480p/final_1080p/subtitle/thumbnail, runpod_volume_id, s3_key 500, s3_endpoint, datacenter, size_bytes, duration_sec, codec VARCHAR(500) reused for multipart UploadId, status, created_at)
videos(id UUID PK, film_id FK, final_asset_id FK, status ENUM draft/proxying/scenes/safety/scripting/tts/assembling/ready/published, target_duration 780, script TEXT, script_hash, youtube_* fields, thumbnail_url)
jobs(id UUID PK, video_id FK, kind ENUM proxy/scene_detect/safety/script/tts/assemble, status ENUM queued/running/completed/failed, inngest_run_id, runpod_job_id, attempts, error)
```

`assets.codec` altered 50→500 for S3 UploadId length. `app/database.py` handles `pool_size=5/max_overflow=10`, `load_dotenv`, `+psycopg` driver.

---

## 5. Implementation Plan — Done vs Left

**DONE (committed, `main` 2 ahead of origin):**
- [x] `feat(api): FastAPI+Inngest+Logfire skeleton` 5a7f902 — `main.py` with `hello_pipeline`/`proxy_film` concurrency 3, `/health`, `/health/db`, `/api/films`, `/api/hello`, `/api/inngest/health`, Logfire `if-token-present`, Inngest dummy signing key for `INNGEST_DEV`
- [x] `feat(db): Neon wiring` 79490b1 — `app/database.py`, `app/models.py`, `alembic/` init, direct/pooled split, migration `0f1518859de0`, `GET /health/db` green, seed `I Am Legend 945c6475… 2007 Francis Lawrence`
- [x] RunPod storage: `tn1qxkkw94` 50GB `EU-RO-1`, S3 creds `user_30hSgon.../rps_CCV7...`, `AWS_S3_ENDPOINT/REGION/VOLUME_ID` in `.env`, `boto3` added, `app/s3.py` (get_client, create_multipart, presigned_part_urls, complete, head fallback), volume verified `put 8 bytes`, `presigned` generated, `HeadObject 403` fallback to `ListObjects` + local size (fix after 403 on `direct_test.bin`)
- [x] Upload slice: `POST /api/uploads/init` (mint multipart, 64MB parts, `codec` stores UploadId), `POST /api/uploads/{id}/complete` (Complete + Inngest fan-out 3), `GET /api/uploads/{id}`, `POST /api/uploads?film_id&kind` direct streaming fallback (bypasses presigned 401 on RunPod S3, handles 1.5GB via `upload_file` multipart, Inngest best-effort thread)
- [x] Single-film ingest: `~/Downloads/Films/I Am Legend ALTERNATE ENDING.../I.Am.Legend...mp4` 1.5G (1506223565) → `s3://tn1qxkkw94/films/945c.../I.Am.Legend.1080p.mp4` via direct (1m59s), `I.Am.Legend.srt` 50559 via `kind=subtitle` → both `available` in Neon assets, `codegraph init` 7 files 116 nodes

**LEFT (in order, concurrency 3 dev):**
- [ ] Proxy 480p — `splicer-proxy` GPU Serverless (`ADA_24`, workers 0→3, PyNvVideoCodec `segmented_transcode`, GOP30, cached decoder) or one-off `runpod_create-pod` `ffmpeg -hwaccel cuda scale=854:480 h264_nvenc` on `tn1qxkkw94`. Then `GET` to pull 480p locally for Blender preview.
- [ ] Knowledge base — TMDB search `6479` + OMDb full plot → `films.metadata` JSONB, parallel search via `parallel/tinyfish/exa/tavily` for reviews/themes.
- [ ] Audio enrichment — `ffmpeg` extract 16k mono → `srt` primary + `whisperx` gaps + `pyannote` diarization + `librosa` RMS → `enrich_scene` fusion per PySceneDetect cut.
- [ ] Hierarchical VLM — Qwen3-VL 8×16 frame batches @128 tokens (362×362) via vLLM `max_num_seqs 64`, Stage1 JSON → Stage2 per-scene summary → Stage3 beats.
- [ ] Script generation — OpenRouter stronger model + `OPENROUTER_API_KEY=sk-or-...` → 14-20 min voiceover.
- [ ] TTS/Assembly — Qwen3-TTS `I.Am.Legend.srt` timing → Blender markers + S3 flagged intervals, NVENC final 1080p.
- [ ] Safety — Shieldstral on final only (~840 frames), blur/mask without breaking narrative.
- [ ] FastAPI Cloud deploy — `fastapi deploy`, dashboard Neon/Logfire integrations, `DATABASE_URL`/`LOGFIRE_TOKEN` encrypted, `INNGEST_SIGNING_KEY` prod.

---

## 6. Key Decisions & Gotchas

- **1 FPS = 5400 not 129k** (24 FPS ×90m). Safety only on final, not source.
- **GPU proxy wins:** NVENC 1072 FPS vs CPU 389 FPS, `RTX 4090 $0.34/h` cheaper per proxy than CPU despite hourly.
- **Presigned 401 on RunPod S3** (`missing Authorization header` for `put_object`/`upload_part` presigned) — fallback to `POST /api/uploads` direct streaming via `boto3.upload_file` (still parallel 3 via async, handles 1.5GB multipart). Keep `init/complete` for later if RunPod fixes.
- **`HeadObject` 403 even when object exists** (list succeeds) — fallback to `ListObjects` or local size.
- **`assets.codec VARCHAR(50)` too small** for RunPod `UploadId` (`1786..._tn1q...`), altered to 500.
- **Concurrency locked to 3** (was 5) via env `PROXY_CONCURRENCY`. Pool size mention: Neon pooled `pool_size=5` → 3 concurrent `INSERT` safe, 30 needs `20`.
- **SQLite not added** — keep Neon-only (free tier) per request.
- **Verda researched but skipped** — CPU cheap but GPU needed for `pynvvideocodec`, Verda storage $0.20/GiB vs RunPod $0.07.
- **Inngest 401 `SendEventsError`** when `inngest dev` not running — caught, returns 202 with warning.

---

## 7. Current State on Disk

```
/home/samir/Downloads/Films/I Am Legend ALTERNATE ENDING (2007) [1080p]/
  I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.mp4 1.5G
  I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.srt 50K
Neon: films 945c6475... I Am Legend, assets 3 (2× source_1080p, 1× subtitle)
S3: s3://tn1qxkkw94/films/945c.../ (3 objects, verified)
.env: RUNPOD_API_KEY, DATABASE_URL pooled, HUGGINGFACE, TMDB_API_KEY+READ, OMDB_API_KEY, INNGEST_SIGNING/EVENT, LOGFIRE_API_KEY, OPENROUTER_API_KEY, AWS S3 trio, RUNPOD_VOLUME_ID
.pi/mcp.json: runpod (hardcoded rpa_80K...), neon/logfire with real tokens (hardcoded), inngest local
.codegraph: 7 files 116 nodes indexed
Git: main 79490b1 ahead of origin by 2, working tree clean after last direct upload (uncommitted: main.py app/s3.py .env .pi/mcp.json, plus srt asset)
```

Provider hiccup fixed (missing `"` in `RUNPOD_VOLUME_ID`, `boto3` added for S3).

---

## 8. Next Agent Instructions

1. `cd splicer && uv sync && uv run alembic upgrade head` (if clean clone: set `.env` from above, ensure `AWS_*` present)
2. `INNGEST_DEV=1 uv run uvicorn main:app --reload` + `curl http://localhost:8000/health/db` → `films:1`
3. For proxy: `runpod_create-pod` or Serverless `splicer-proxy` on `tn1qxkkw94` EU-RO-1, transcode `I.Am.Legend.1080p.mp4` → `480p_proxy.mp4` on same volume, then `aws s3 cp s3://tn1qxkkw94/.../480p_proxy.mp4 ~/Downloads/` for local Blender.
4. Enrich: `GET /3/search/movie?query=I Am Legend` → `6479` → `GET /3/movie/6479?append_to_response=credits` + OMDb `?i=tt0480249&plot=full` → update `films.metadata`.
5. Follow Grok hierarchical + audio SDK list: `ffmpeg-python`, `faster-whisper`, `whisperx`, `pyannote.audio`, `librosa`, `pydub`, `moviepy`, `scenedetect`, `srt`.

Commit after each slice: `feat(upload): ...`, `feat(proxy): ...`, etc. Add `.pi/mcp.json` to `.gitignore` before pushing (contains `rpa_...`).

---
