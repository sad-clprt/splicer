# Splicer Pipeline Completion Plan

## Goal
Complete the automated 90 min → 14–20 min voiceover-only recap pipeline on the existing stack (FastAPI + Inngest + Neon + RunPod) using film `945c6475...` (I Am Legend) as the first end-to-end canary: `s3://tn1qxkkw94/films/945c.../I.Am.Legend.1080p.mp4` (1.5 GB) + `.srt` already in Neon/S3, through proxy → KB → audio → VLM → script → TTS/Blender → safety → FastAPI Cloud deploy, with concurrency `3` and no original audio/music in the final.

## Success Criteria
- Proxy: `proxy_film` Inngest fn reliably produces `proxy_480p` at `films/<id>/I.Am.Legend.480p_proxy.mp4` on volume `tn1qxkkw94` EU-RO-1, verified via `list_objects_v2`, and locally pullable for Blender preview.
- KB: `films.metadata` JSONB for `945c6475...` populated from TMDB `6479` (`/3/search/movie`+`/3/movie/6479?append_to_response=credits`) + OMDb `tt0480249&plot=full` + 1–2 Parallel/TinyFish sweeps, queryable.
- Audio enrichment: `srt` primary + `whisperx` gap-fill + optional `pyannote`/`librosa` fusion per `PySceneDetect` cut is produced; `enrich_scene` contract defined.
- VLM: 1 FPS (5400 frames, NVDEC 2-thread 4090 GOP30, device-mem 362×362 128 tok) → 675×8-frame batches via vLLM `Qwen3-VL-8B` `max_num_seqs 64` → Stage1 JSON → Stage2 per-scene → Stage3 beats stored (DB or S3 pointer) and reproducible.
- Script: OpenRouter stronger model generates 14–20 min voiceover script (target `videos.target_duration_sec=780` expandable to 840–1200) from Stage3+KB+audio.
- TTS/Assembly: `Qwen3-TTS-12Hz-1.7B-CustomVoice` renders voiceover aligned to SRT timing; Blender Python assembly + NVENC 1080p final with markers + flagged S3 intervals.
- Safety: `Shieldstral-1.0-3B` runs only on final recap (~840–1200 frames @1 FPS), not source 90 min; blurs/masks without breaking narrative.
- Deploy: `fastapi deploy` with Neon/Logfire integrations; `INNGEST_SIGNING_KEY` prod, `/health` + `/health/db` green on FastAPI Cloud.

## Context And Current Facts
- **Deep research (2026-08-11, 6 workflows, `.agents/research/deep-research-2026-08-11.md` + `.agents/research/runpod-optimization.md`):** RunPod `tn1qxkkw94` live `STANDARD` EU-RO-1, `ADA_24` `HIGH`/`MEDIUM`, model caching vs baked vs network volume, `Qwen3-VL-8B` (8.77B, 256K→1M, 128 tok@362 default), `Shieldstral-1.0-3B` (Ministral+Pixtral, single forward `yes/no` softmax), `WhisperX` `v3.8.7rc1` (VAD+batched faster-whisper+WAV2VEC2 align, 70×, `>=3.10,<3.14` vs `3.14.2` risk), final export `edit_decision.json` + Blender headless `GAUSSIAN_BLUR` `bpy`, YouTube YPP `reused/inauthentic` allowed vs not-allowed (voiceover-only, sub-10s cuts, blur gore) gathered via `support.google.com` + `runpod-docs` MCP + `hf models info/card` + Tavily. Research drives revisions below.
- **Committed:** `main` 2 ahead of origin: `5a7f902` FastAPI+Inngest+Logfire skeleton (`main.py` lifespan, `hello_pipeline`/`proxy_film` `concurrency=[limit=3]` retries 3, `/health`/`/health/db`/`/api/films`/`/api/hello`/`/api/inngest/health`, Logfire `if-token-present`, `INNGEST_DEV` dummy `signkey-test-fake`), `79490b1` Neon wiring (`app/database.py` pooled `DATABASE_URL` → `+psycopg`, `pool_size=5/max_overflow=10`, `DATABASE_URL_DIRECT` strips `-pooler`, `app/models.py` `Base` with `films/assets/videos/jobs`, Alembic `0f1518859de0`). Verified via `HANDOFF.md §4-5` and inspected `main.py:44-131`, `app/database.py:18-48`, `app/models.py:60-155`, `alembic/env.py:17-24`.
- **S3/Volume:** `app/s3.py` (`get_s3_client` boto3 `s3v4`, `S3_ENDPOINT https://s3api-eu-ro-1.runpod.io`, `VOLUME_ID tn1qxkkw94`, `s3_key_for_film`, `create_multipart_upload`/`presigned_part_urls`/`complete_multipart_upload`/`head_object_safe`). `.env` holds `RUNPOD_API_KEY`, `AWS_S3_ENDPOINT/REGION/VOLUME_ID`, `LOGFIRE_TOKEN`, `DATABASE_URL`. `scripts/upload_srt.py` is existence proof for direct `upload_file` + `list_objects_v2` pattern.
- **Upload slice (uncommitted on `main`):** `POST /api/uploads/init` (64 MB parts, `asset.codec=UploadId` reuse), `POST /api/uploads/{id}/complete` (HeadObject fallback, Inngest `film/proxy.requested` fan-out via `threading`+`asyncio`), `GET /api/uploads/{id}` (live `head_object_safe`), `POST /api/uploads?kind=...` direct streaming fallback (handles presigned 401, 1.5 GB multipart). Verified: ingest of `I.Am.Legend.1080p.mp4` and `.srt` via direct → both `available`; code is in working-tree `main.py:234-549` not yet committed.
- **Gotchas proven in handoff/repo:** presigned `401 missing Authorization` on RunPod S3 retained init but fallback required (`HANDOFF.md §6`); `HeadObject 403` even when exists → `list_objects_v2` fallback (`app/s3.py:64-68`, `main.py:485-498`); `assets.codec VARCHAR(50)` too small for `UploadId` — handoff claims altered 50→500 but inspected `alembic/versions/0f1518859de0` line 51 still `sa.String(50)` and `app/models.py:100` `String(50)` so mismatch persists; pool size `5` safe for `3` concurrent but needs `20` for `30`; `Inngest 401` caught as `202` warning (`main.py:559-569`); SQLite not added (Neon-only).
- **Working tree:** `M main.py, M pyproject.toml, M uv.lock, ?? app/s3.py, ?? scripts/, ?? .codegraph/, ?? HANDOFF.md` per `git status`. `.codegraph/` indexed (7 files 116 nodes). `.pi/mcp.json` not gitignored yet (contains `rpa_...` per handoff `§2`). `tests/` dir listing empty, `pyproject.toml` dev deps `pytest>=9.0.3, ruff>=0.15.14, ty>=0.0.38`. `alembic.ini` `prepend_sys_path=.`.
- **Seed:** Neon `films 945c6475-a629-4140-9968-9135d716565d` I Am Legend 2007 Francis Lawrence; assets 3 (`2×source_1080p` + `1×subtitle`); S3 `s3://tn1qxkkw94/films/945c.../` 3 objects.

## Constraints And Non-goals
- Keep Neon-only; no SQLite addition.
- Respect Inngest `concurrency=3` in dev, env-tunable to 30 later (Neon pool bump required). Keep `LOGFIRE_TOKEN` injection via FastAPI Cloud; console fallback locally.
- Blobs never in Postgres — only `assets` pointers.
- Safety strictly on final 14–20 min (840–1200 frames), never full 90 min.
- No frontend beyond `/docs`.
- **Non-goals this slice:** multi-film scale, YT publish automation beyond `videos.youtube_*`, Verda switch, custom VLM training, sqlite fallback, thumbnail pipeline v2. No whole-file `muse.write_file` rewrites; no `no_ignore:true` searches.

## Key Decisions
1. **Proxy compute: Serverless `splicer-proxy` (ADA_24/GOP30/PyNvVideoCodec `segmented_transcode`) as primary, `runpod_create-pod` one-off ffmpeg `hwaccel cuda scale=854:480 h264_nvenc` as fallback.**
   - *Why:* Handoff benchmark `PyNvVideoCodec 1072 FPS` vs `ffmpeg 389 FPS` on L40G; `RTX4090 $0.34/h` cheaper per proxy than CPU Verda `CPU.4V $0.0279/h` needs 4×+ slower. Serverless gives queue fan-out 3; pod fallback validates volume S3 path without Serverless config.
   - *Rejected:* CPU-only Verda (needs `pynvvideocodec` GPU) and pure ffmpeg without cached decoder (7.2× slower on short clips per handoff).

2. **Keep `POST /api/uploads` direct streaming as canonical; retain `/init`+`/complete` for later if RunPod fixes presigned.**
   - *Why:* Presigned 401 proven; direct already ingested 1.5 GB in `1m59s`. Less round-trip, still parallel 3 via async.
   - *Rejected:* Force-only-presigned (blocked) or client-side chunk reassembly in FastAPI memory (OOM).

3. **KB merge strategy: TMDB+OMDb as ground truth, Parallel/TinyFish/Exa/Tavily as enrichment into `films.metadata_json` with source stamps.**
   - *Why:* Natural Q `What is I Am Legend about?` + credits + full plot covers characters/themes; web enrichment adds reviews/themes without overwriting canonical IDs. Matches handoff `§4 metadata JSONB` and available global `.env` keys.
   - *Rejected:* Web-only KB (unstable) or TMDB-only (misses long plot).

4. **Audio: SRT primary, WhisperX only gaps, `pyannote`/`librosa` optional.**
   - *Why:* SRT 50 KB already available; WhisperX expensive; diarization+energy only where subtitle gaps exist per handoff `enrich_scene` fusion.
   - *Rejected:* Full WhisperX re-transcribe (cost + drift).

5. **VLM tokens: 362×362/128 tok default, 512×512/256 tok escalate path, patch16 merge2 32×, no tiling, 8-frame batches, `max_num_seqs 64`.**
   - *Why:* Handoff specifies 5400 frames→675 clips; 128 tok saves 2× vs 256 while still grounding; vLLM batch saturates 24 GB VRAM.
   - *Rejected:* 129k frames at 24 FPS (too much), or 1-frame-per-scene (loses motion).

6. **Script LLM via OpenRouter stronger model (not Qwen-VL).**
   - *Why:* Qwen-VL only for visual grounding per handoff; stronger LLM handles narrative arc to 14–20 min timing.
   - *Rejected:* End-to-end VLM script (weak storytelling).

7. **TTS last before assembly; Blender+N VENC for final.**
   - *Why:* Script timing determines cut points; TTS after script final avoids re-render.

8. **Safety filter placement after final 1080p encode.**
   - *Why:* Shieldstral 840–1200 frames vs 5400/129k saves cost, masks can re-blur final without VLM re-run.

9. **Migration fix: new Alembic revision `codec 50→500` required despite handoff claim.**
   - *Why:* Repo still `50` on both model and initial migration; real `UploadId` length `1786..._tn1q...` overflows.
   - *Rejected:* Silent `String(500)` model-only without DB migration (drift).

10. **RunPod model caching — Cached Models (host `/runpod-volume/huggingface-cache`, not billed, seconds) as primary for all HF models; Network Volume only for film assets.**
   - *Why:* Live probe + docs priority `Cached → Baked → Network Volume`; cache is host-local before worker start (unbilled), faster than network NFS even though same mount. VLM/TTS/Safety are HF → cached; film assets → `tn1qxkkw94` S3. Init outside handler, FlashBoot ON, `HF_HUB_OFFLINE=1 local_files_only`.
   - *Rejected:* Network volume for models (billed, slower), baking into image (10–50 GB push, rebuild).

11. **Final export: JSON EDL (`edit_decision.json`) → volume S3 → Serverless Blender headless (`blender --background --python assemble.py`) + PyNvVideoCodec NVDEC/NVENC, not `.blend` payload.**
   - *Why:* Payload ~20 MB limit vs 1.5 GB original; proxy/original must share FPS/GOP30 (`ffprobe` validate, `scene.render.fps` matched before any strip); worker mounts `/runpod-volume` (not `/workspace`), translates S3 keys, applies `new_movie`/`new_sound`/`GAUSSIAN_BLUR` masks per `markers`/`safety_flags` `{t0,t1,bbox fix score}`, exports `h264_nvenc vbr_hq cq23 8M/12M 1920×1080 gop30 aac 384k yuv420p high 4.2` per YouTube `answer/1722171`. User polishes 480p proxy timeline locally with JSON → `bpy.ops.marker.add()` (frame=`time_sec*fps`), passes final JSON to serverless for 1080p fetch/apply.
   - *Rejected:* Shipping `.blend` binary or ffmpeg-only cuts (loses marker audit, drifts FPS).

12. **YouTube monetization: voiceover-only + sub-10s cuts + cohesive narrative + blur safety regions = `reused` pass.**
   - *Why:* `support.google.com/answer/1311392` reused allowed = `scene where you’ve rewritten dialog and changed voiceover` (splicer core), plus substantive storyline+editing; not allowed = stitched clips little narrative. Techniques: no original audio/music (meaningful difference), cut every 3–5s, hold single frame via WhisperX TTS timings, distinct act arc via stronger LLM, `GAUSSIAN_BLUR`/`boxblur` with 10% margin for gore/nudity flagged by Shieldstral bbox (allowed if blurred, not shock-intent), 14–20m length, description fair-use statement, thumb no sensational gore. Content ID may still claim — dispute with 4-factor fair use.
   - *Rejected:* Unblurred gore in first 30s, template repetitious recaps (`inauthentic` policy).

13. **WhisperX double-run: gap-fill source + re-run on final TTS for captions → edit pacing.**
   - *Why:* Fixes Whisper utterance timestamps → word-level via wav2vec2 `WAV2VEC2_ASR_LARGE_LV60K_960H`, VAD batching 70×, `large-v2 <8GB`, `pyannote` diarization. Post-TTS `[{word,start,end}]` drives `cut` where pause>0.5s / `hold` where beat needs emphasis — aligns script ↔ final video for transformative edit. Risk: `whisperx >=3.10,<3.14` vs splicer `3.14.2` — isolate to worker image or pin Python 3.11 for workers.
   - *Rejected:* `faster-whisper` alone without alignment (good but loses batch+VAD purity).

## Recommended Approach
Sequenced thin vertical slice per `HANDOFF.md §8` + research EDL flow with I Am Legend as single canary; each slice commits alone (`feat(proxy):`, `feat(kb):`, …) and adds `.pi/mcp.json` to `.gitignore` before any push. Keep `INNGEST_DEV=1` + `uv run uvicorn main:app --reload` loop; verify `curl /health/db` → `films:1` before each GPU step. Implement Inngest durability per stage (`ctx.step.run` + `ctx.step.parallel` fan-out), Logfire spans, and Neon `jobs` mirrors (`queued`/`running`/`completed`/`failed`). Prefer `boto3` `list_objects_v2` after every S3 write (HeadObject 403 fallback). Introduce thin service modules `app/proxy.py`, `app/kb.py`, `app/audio.py`, `app/vlm.py`, `app/script.py`, `app/tts.py`, `app/safety.py` imported by `main.py` rather than bloating `main.py`; keep `app/database.py` pool logic and `DATABASE_URL` direct for Alembic. All HF models use **Cached Models** (host `/runpod-volume/huggingface-cache`, not billed) with `HF_HUB_OFFLINE=1`, init outside handler, FlashBoot ON, `ADA_24` `REQUEST_COUNT` for VLM fan-out vs `QUEUE_DELAY` for proxy. Final export builds from `edit_decision.json` (scenes/markers/safety_flags/script/export) per research §3 — Blender headless `GAUSSIAN_BLUR` bboxes, NVENC `8M/12M 1080p gop30 aac 384k yuv420p`, WhisperX re-run on TTS for pacing.

## Work Plan

### Phase 0 — Repo hygiene & migration (prerequisite, ½ day)
- **Scope:** `git add .gitignore` for `.pi/mcp.json`+`.codegraph/`+`.env`; new migration `codec VARCHAR(500)` (alter `assets.codec`), align `app/models.py:100` to `500`; `uv sync && uv run alembic upgrade head`; `uv run ruff check`/`ty check` baseline.
- **Dep:** none. Blocks proxy uploadId persistence.
- **Files:** `.gitignore`, `app/models.py`, `alembic/versions/<new>_codec_500.py`, `pyproject.toml` (if lint fixes).
- **Commit:** `fix(db): enlarge assets.codec for RunPod UploadId`.

### Phase 1 — Proxy 480p end-to-end (1–2 days, highest risk)
- **Scope:** Flesh `proxy_film` (`main.py:112-128`) from `touch` stub to real: `app/proxy.py` `transcode_480p(s3_key)->proxy_key` using either Serverless handler (`segmented_transcode`, GOP30, cached decoder 7.2×) or pod `ffmpeg -hwaccel cuda -i <src> -vf scale=854:480 -c:v h264_nvenc -g 30 -c:a aac <dst>` on `tn1qxkkw94`. `POST /api/uploads/complete` already fires `film/proxy.requested`; add `GET /api/proxy/{film_id}` status reading `jobs`+`assets(kind=proxy_480p)`+S3 list. Concurrency 3 test: 3 parallel `proxy.requested` events (or 2× upload + 1× proxy). ENV `PROXY_CONCURRENCY`, `RUNPOD_VOLUME_ID`, `AWS_S3_*`.
- **Dep:** Phase 0.
- **Reuse:** `app/s3.py` `head_object_safe`, `main.py:354-404` Inngest send pattern.
- **Commit:** `feat(proxy): wire RunPod 480p proxy via Inngest durable`.

### Phase 2 — Knowledge base → `films.metadata` (1 day, parallelizable after Phase 0)
- **Scope:** `app/kb.py` `enrich_film(film_id)` → TMDB `GET /3/search/movie?query=I Am Legend→6479`, `GET /3/movie/6479?append_to_response=credits`, OMDb `?i=tt0480249&plot=full`, Parallel/TinyFish sweep `What is I Am Legend about?` (cast/characters/themes), merge into `films.metadata_json` with `{tmdb, omdb, web:{parallel:…}, fetched_at}`. Endpoint `POST /api/films/{id}/enrich`. Handle `tmdb_id/imdb_id` unique constraints.
- **Dep:** Phase 0 only (can run parallel to Phase 1).
- **Reuse:** `requests`, existing `.env` `TMDB_API_KEY`+`OMDB_API_KEY`+search keys.
- **Commit:** `feat(kb): enrich films.metadata from TMDB/OMDb/web`.

### Phase 3 — Audio enrichment + scene boundaries (1–2 days)
- **Scope:** `app/audio.py` `enrich_audio(film_id)`: `ffmpeg -i source_1080p -ar 16000 -ac 1 mono.wav` extract, parse existing `srt` (from `kind=subtitle` asset), `PySceneDetect ContentDetector/AdaptiveDetector` → boundaries, `whisperx` fill gaps, `pyannote.audio` diarization + `librosa` RMS where `srt` missing, output per-scene JSON `enrich_scene` (visual slot empty). Store as S3 `films/<id>/audio_enrich.json` + pointer in `jobs` or new `assets` kind? Use `videos.script` placeholder or `jobs.error` log. Add `POST /api/films/{id}/enrich-audio`.
- **Dep:** Phase 1 (needs `proxy_480p` or `source_1080p` bytes local via S3 `get_object` or volume mount). Phase 2 metadata optional but helps character diarization labels.
- **Deps added:** `scenedetect`, `ffmpeg-python`, `whisperx`/`faster-whisper`, `pyannote.audio`, `librosa`, `pydub`, `srt` per `HANDOFF.md §8.5` — isolate to worker image, not FastAPI prod.
- **Commit:** `feat(audio): scene+subtitle+diarization enrichment`.

### Phase 4 — Hierarchical VLM (2–3 days, costliest)
- **Scope:** `app/vlm.py` worker (RunPod Serverless, vLLM `Qwen3-VL-8B-Instruct`, `hf models info` 8.77B 256K→1M `Interleaved-MRoPE`/`DeepStack`/`Text–Timestamp`, `flash_attention_2` bfloat16, `transformers` git): Stage1 per 8-frame clip → JSON `{chars, actions, importance}`, 8-frame batches `max_num_seqs 64` 128 tok@362 (256@512 escalate only if grounding low, patch16 merge2 32× no tiling), Stage2 fuse per scene (+ SRT+pyannote+KB), Stage3 beats. Image `vllm v0.8+`, endpoint `splicer-vlm` `ADA_24` **Cached Model** `Qwen/Qwen3-VL-8B-Instruct` (host `/runpod-volume/huggingface-cache`, not billed, `HF_HUB_OFFLINE=1`), `REQUEST_COUNT` scaler 1 for 675 fan-out, FlashBoot ON. Input 1 FPS via `PyNvVideoCodec` device-mem resize (2 NVDEC threads GOP30 1072 FPS). Output S3 `films/<id>/vlm/{stage1,stage2,stage3}.json` + Inngest `scene_detect` `step.parallel` batch 32, Logfire token budget.
- **Dep:** Phases 1+3 (frames + per-scene audio). Phase 2 KB for Stage2 fusion.
- **Commit:** `feat(vlm): hierarchical Qwen3-VL 5400→675→scene→beats`.

### Phase 5 — Script generation (1 day)
- **Scope:** `app/script.py` + `POST /api/videos/{id}/script`: prompts OpenRouter (`OPENROUTER_API_KEY`) stronger model with Stage3 beats+KB+audio enrichment, constraints: 14–20 min spoken (≈2100–3000 words @150 wpm), voiceover-only, no original audio/music, narrative arc. Persist to `videos.script`+`script_hash`+`target_duration_sec` (780→840–1200). Include `ctx.step.run` for retry and Logfire trace of prompt hash.
- **Dep:** Phases 2+4.
- **Commit:** `feat(script): OpenRouter voiceover script from beats`.

### Phase 6 — TTS + Blender/NVENC assembly (2 days)
- **Scope:** `app/tts.py` RunPod TTS worker `Qwen3-TTS-12Hz-1.7B-CustomVoice` (Cached Model, `ADA_24`, not billed load) → wav aligned to `srt` timing; **WhisperX re-run on final TTS wav** → `[{word,start,end}]` captions → pacing EDL (`cut` pause>0.5s, `hold` emphasis). Blender headless via `edit_decision.json` on volume S3 (`film_id fps proxy_s3_key original_s3_key scenes markers safety_flags script export`) — worker mounts `/runpod-volume` (not `/workspace`), validates `ffprobe` fps/GOP30 both sources before `bpy`, creates `sequence_editor` `new_movie/new_sound/GAUSSIAN_BLUR` masks per `bbox` (+10% margin), keeps proxy/original FPS/timebase sync. NVENC final `h264_nvenc vbr_hq cq23 8M/12M 1920×1080 gop30 aac 384k yuv420p high 4.2` per YouTube `answer/1722171`. Output `videos(final_asset_id)` → `assets(kind=final_1080p)` + thumbnail on volume. Endpoint `POST /api/videos/{id}/assemble` enqueues Inngest `tts`→`assemble` (`queued/running` in `jobs`). User workflow: polish 480p proxy locally with JSON → `bpy.ops.marker.add()` (frame=`time_sec*fps`), push JSON to S3, Serverless fetches original 1080p for 1080p export.
- **Dep:** Phase 5 (script). Safety Phase 7 bbox can also be pre-filled but final blur after export allowed.
- **Commit:** `feat(assemble): TTS+WhisperX captions+Blender headless NVENC final`.

### Phase 7 — Safety on final only (1 day)
- **Scope:** `app/safety.py` RunPod worker `Shieldstral-1.0-3B` (`hf models info` 3.84B Ministral+Pixtral, single token `yes/no` softmax `logprobs=True top_logprobs 20`, threshold 0.5, 16 GB BF16, `vllm serve --max-model-len 32768`) — Cached Model `ADA_24`. Runs ONLY on final 14–20 min `@1 FPS` (840–1200 frames) vs 5400/129k — cost saved. Query `Does this content contain blood/extreme violence/nudity?` + strict instruct, image+text sandwich, maps to `[{t0,t1,category,score,fix:gaussian_blur,bbox:{x,y,w,h},reason}]` → appendix to `edit_decision.json` `safety_flags` + `markers(type=safety)`. Blur via `GAUSSIAN_BLUR`/`boxblur` masked to bbox, narrative preserved (audio continues). Gate `videos.status` `safety→ready`. Include YouTube monetization note: blurred = advertiser-friendly (not shock-intent) per `answer/9288567`; keep audit `score` for dispute.
- **Dep:** Phase 6 (final 1080p). Can run as post-process re-encode (no VLM re-run).
- **Commit:** `feat(safety): Shieldstral single-pass final-only bboxes`.

### Phase 8 — FastAPI Cloud deploy & hardening (½ day)
- **Scope:** `fastapi deploy` with Neon/Logfire dashboard integrations; set prod `INNGEST_SIGNING_KEY`/`EVENT_KEY`, verify `DATABASE_URL` pooled injected, `LOGFIRE_TOKEN` encrypted, `INNGEST_DEV` unset. Add `GET /health/db` + `/api/films` smoke on cloud URL, Inngest prod URL registration. Bump `app/database.py pool_size 20` doc for `concurrency 30` via env.
- **Dep:** Phases 1–7 green locally.
- **Commit:** `chore(deploy): FastAPI Cloud + prod Inngest/Logfire`.

PR/commit split is binding per user rule: one commit per phase above in order; do not collapse Phases 2+3 or 5+6.

## Validation Plan
- **Phase 0:** `uv run alembic upgrade head` then `psql $DATABASE_URL_DIRECT -c "\d assets"` shows `codec varchar(500)`; `uv run ruff check app` and `uv run ty check` pass; `git status` shows `.pi/mcp.json` ignored.
- **Phase 1:** `INNGEST_DEV=1 uv run uvicorn main:app --reload` + 3× `curl -X POST /api/inngest` or `POST …/complete` triggering `film/proxy.requested`; Inngest UI shows 3 concurrent `proxy_film` runs `completed` (requires `splicer-mcp` `inngest` MCP live via `inngest dev -u http://localhost:8000/api/inngest`); `aws s3 --endpoint-url https://s3api-eu-ro-1.runpod.io ls s3://tn1qxkkw94/films/945c.../` lists `480p_proxy.mp4` with size; `GET /api/uploads/{proxy_asset_id}` `live.exists:true`; `curl …/480p_proxy.mp4 --output /tmp/xxx && ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,avg_frame_rate -of csv` ⇒ `854,480,h264,24/1` (FPS preserved, `ffprobe` both sources before bpy).
- **Phase 2:** `curl -X POST /api/films/945c.../enrich` → `200`; `psql -c "select metadata->'tmdb'->>'id', metadata->'omdb'->>'Title' from films"` returns `6479 / I Am Legend`; Logfire trace shows TMDB+OMDb latency.
- **Phase 3:** `aws s3 ls …/audio_enrich.json`; local `python -c "import json;print(json.load(open(...))['scenes'][:2])"` shows scene boundaries matching `PySceneDetect` + subtitle slice; gap fill count logged. Verify `splicer-mcp` `neon` MCP `select count(*) from films` before/after.
- **Phase 4:** Endpoint uses **Cached Model** `/runpod-volume/huggingface-cache/hub/models--Qwen--Qwen3-VL-8B-Instruct` (host, not billed) — verify `runpod` MCP `get-endpoint` shows `modelReference Qwen/Qwen3-VL-8B-Instruct`; Logfire span `vlm.stage1` count `675` + `vlm.stage2` scene count; spot-check `stage1` JSON for `chars/actions/importance` on 3 known scenes (e.g., lab, empty streets); token avg `~128` token budget logged; `hf models info` matches card.
- **Phase 5:** `GET /api/videos/{id}` script length `2100–3000 words`, `script_hash` set, `target_duration_sec` 780–1200; manual read confirms voiceover-only, no original-audio instructions, covers alternate ending, cohesive narrative per monetization check (`support.google.com/answer/1311392` reused allowed = rewritten dialog + voiceover).
- **Phase 6:** `edit_decision.json` on volume S3 valid JSON (check `export fps==source fps` via `ffprobe` both); final `assets` `final_1080p` size+MIME via `list_objects_v2`; `ffprobe` `1920x1080` + `8M/12M` bitrate (`ffprobe -show_streams -select_streams v:0 -show_entries stream=bit_rate,width,height,codec_name`); audio single TTS only (`ffprobe -show_streams | grep -c a:0` ==1, `grep -c lyric` 0); markers imported locally `bpy.ops.marker.add()` count == JSON `markers` length; JSON `safety_flags` bbox visual sample via frame dump blurred+10% margin.
- **Phase 7:** Shieldstral endpoint cached `mistralai/Shieldstral-1.0-3B` (`vllm serve --max-model-len 32768 logprobs`) — verify `runpod` MCP `list-endpoints`; `s3://…/edit_decision.json` `safety_flags` appended (`score` 0–1), flagged intervals <5% runtime; re-encoded final visually blurs flagged frames (sample 2 intervals screenshot/frame dump); `videos.status=ready`; `unsafe_score` threshold 0.5 audit logged for dispute.
- **Phase 8:** `curl https://<fastapi-cloud>.run.app/health/db` → `{"status":"ok","films":1}`; `/docs` reachable; `POST /api/hello` enqueues Inngest prod event returns `queued:true`; Neon/Logfire integrations green.

**Highest-risk validation:** Phase 1 proxy 480p GPU path on RunPod (S3 401/403 fallbacks, NVDEC GOP30, volume mount, Inngest fan-out 3) — failure blocks all downstream.

## Risks / Rollback
- **RunPod S3 401/HeadObject 403 regressions:** Mitigate by keeping `head_object_safe`+`list_objects_v2` dual check; rollback to direct streaming only; no data loss (source stays). Monitor Logfire `s3.*` warn rates via `splicer-mcp` `logfire` MCP.
- **Alembic drift (`codec 50→500`):** New migration is reversible `downgrade` to `50`; pre-deploy backup via `alembic downgrade -1` test on staging Neon branch.
- **GPU OOM in VLM/TTS (24 GB):** Pin `max_num_seqs 64` and 8-frame batches 128 tok, `flash_attention_2`, `HF_HUB_OFFLINE`; fallback downscale 362 or `int8`; isolate `whisperx` Python 3.11 worker image (splicer 3.14.2 incompatible per research). Logfire GPU mem spans.
- **Inngest dev vs prod key confusion:** Keep `INNGEST_DEV=1` dummy locally; prod key only in FastAPI Cloud env. Rollback: unset `INNGEST_DEV` locally reproduces prod error in 202→failure fast. Use `splicer-mcp` `runpod` MCP `stream-worker-logs` to inspect.
- **Rate limits TMDB/OMDb/OpenRouter:** Cache `films.metadata` with `fetched_at`; retry with backoff; rollback by disabling web enrichment flag.
- **Safety over-filter / YouTube reused demonetization:** Human review gate before `ready→published`; flagged intervals logged pre-mutation with `score` audit; re-run without blur if narrative broken. Validate against `reused` allowed (`rewritten dialog+voiceover`) vs `inauthentic` template — check reused decision before publish.
- **Push secret leak:** `.pi/mcp.json` ignored before any `git push`; pre-commit hook `git diff --cached --name-only | grep -q ".pi/mcp.json" && exit 1`. Verify via `runpod` MCP `get-billing` shows volume still $3.50/mo (not leaked delete).
- **FPS drift proxy/original:** Validate `ffprobe fps` match before any `bpy` strip; mismatch abort assemble — avoids timebase drift.

## Open Questions
- WhisperX Python pin: worker image needs Python `3.11` (or `3.12`) for `ttml2srt`/`pyannote` while splicer API stays `3.14.2` — confirm isolation via separate Dockerfiles vs `uv` override.
- Confirm during Phase 1 whether to keep Serverless `ADA_24 community $0.34` vs `secure $0.74` for prod; run one-off pod benchmark first. No other blocking questions — handoff volume ID/endpoint, seed IDs, SDK list plus deep research model configs verified.
