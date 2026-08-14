# Splicer: Next Steps Analysis

## Current State ✓

**Completed:**
- ✅ Architecture migrated (FastAPI/Inngest → Sequential Python)
- ✅ Database simplified (Neon Postgres → SQLite)
- ✅ Dependencies cleaned (15+ → 8 packages)
- ✅ Pipeline stages created (00 through 10)
- ✅ Knowledge enrichment added (TMDB + OMDB)
- ✅ All 5 RunPod endpoints configured and scaled to 0
- ✅ All API credentials present in .env

**RunPod Endpoints (all ADA_24, workers=0/0):**
1. `splicer-proxy` (2dmz605z5wxjo1) — Proxy generation
2. `splicer-audio-hub` (0jj6liixhjnhbh) — WhisperX
3. `splicer-vlm-hub` (i5xjuwuikr335p) — Qwen3-VL
4. `splicer-tts-hub` (5fb99jvt01k63a) — TTS
5. `splicer-safety-hub` (yams2crmm7o6l9) — Shieldstral

## Critical Decision Point: What to Tackle First?

### Option A: Deploy Proxy Endpoint (Your Suggestion) ⭐ RECOMMENDED
**Why this makes sense:**
- Proxy generation is the first GPU stage (stage 01)
- Blocks everything downstream (audio, VLM, etc. need the proxy)
- Tests the full RunPod deployment → job submission → polling flow
- Validates our RunPod SDK integration
- Once working, we have a proven pattern for other endpoints

**What's needed:**
1. **Check current proxy endpoint status**
   - Does it already have a worker image?
   - What's the current configuration?
   - Is it using Hub worker or custom Dockerfile?

2. **If custom image needed:**
   - Write Dockerfile with ffmpeg + h264_nvenc
   - Handler function for transcode job
   - Deploy via GitHub or local build + push

3. **If Hub worker exists:**
   - Find ffmpeg/video transcoding worker on RunPod Hub
   - Configure endpoint with correct env vars
   - Test with our canary film

**Estimated effort:** 2-4 hours (depending on if image exists)

### Option B: Test Full Pipeline with Stubs
**Approach:**
- Mock proxy/audio/VLM/TTS stages to return fake data
- Test end-to-end orchestration flow
- Verify database state tracking works
- Then replace mocks with real endpoints one by one

**Pros:** Tests architecture first, hardware later  
**Cons:** Doesn't validate RunPod integration

### Option C: Integrate Script Generation First
**Approach:**
- Skip GPU stages, focus on lightweight local work
- KB enrichment (done) → Script generation → Verify output quality
- Test OpenRouter integration
- Add more enrichment sources if needed

**Pros:** Fast feedback on script quality  
**Cons:** Can't see how it works with real VLM beats

---

## Recommendation: Option A (Deploy Proxy Endpoint)

### Execution Plan

#### Phase 1: Investigate Current Proxy Endpoint (15 min)
```bash
# Check endpoint details
uv run python << 'EOF'
import runpod
runpod.api_key = "rpa_80KHF9RV2VJQTLNR00APD70CMM38Y847P0MNIB0By36hyi"
ep = [e for e in runpod.get_endpoints() if e['id'] == '2dmz605z5wxjo1'][0]
print(f"Name: {ep['name']}")
print(f"Image: {ep.get('imageName', 'NOT SET')}")
print(f"Template: {ep.get('templateId', 'NOT SET')}")
print(f"GPU: {ep.get('gpuIds')}")
print(f"Workers: {ep['workersMin']}/{ep['workersMax']}")
EOF

# Check if it has a handler
uv run python -m src.runpod_client # (we'd add an endpoint inspect method)
```

**Decision tree:**
- **If image/template exists** → Test job submission immediately
- **If no image** → Deploy custom handler

#### Phase 2A: If Custom Image Needed (2-3 hours)
1. **Create handler** (`handlers/proxy/handler.py`)
   - Input: `{s3_key, target_width, target_height, codec, crf, preset}`
   - Download from S3
   - Transcode with ffmpeg h264_nvenc
   - Upload result to S3
   - Return: `{proxy_key, size_bytes}`

2. **Create Dockerfile** (`handlers/proxy/Dockerfile`)
   - Base: `runpod/pytorch:2.8.0-py3.11-cuda12.8.1-devel-ubuntu24.04`
   - Install: ffmpeg with NVENC support
   - Copy handler

3. **Deploy**
   ```bash
   cd handlers/proxy
   docker build --platform linux/amd64 -t <username>/splicer-proxy:v1 .
   docker push <username>/splicer-proxy:v1
   # Update endpoint via RunPod console or API
   ```

4. **Test**
   ```bash
   uv run python -m src.stage_01_proxy_generate \
     945c6475-a629-4140-9968-9135d716565d \
     films/945c6475-a629-4140-9968-9135d716565d/I.Am.Legend.1080p.mp4
   ```

#### Phase 2B: If Hub Worker Exists (30 min)
1. Search RunPod Hub for ffmpeg/video worker
2. Configure endpoint with found worker
3. Test immediately

#### Phase 3: Validate End-to-End (30 min)
```bash
# Full proxy flow test
film_id="945c6475-a629-4140-9968-9135d716565d"
source_key="films/${film_id}/I.Am.Legend.1080p.mp4"

# Stage 00: Check source
uv run python -m src.stage_00_check_source $film_id $source_key

# Stage 01: Submit proxy job
job_id=$(uv run python -m src.stage_01_proxy_generate $film_id $source_key | grep "job submitted" | awk '{print $NF}')

# Stage 02: Poll and download
uv run python -m src.stage_02_proxy_download $film_id $job_id ./output
```

**Success criteria:**
- ✅ Job submits without error
- ✅ Workers spin up (check endpoint health)
- ✅ Job completes (status → COMPLETED)
- ✅ 480p proxy downloads successfully
- ✅ DB records asset correctly

---

## Alternative: If Proxy Takes Too Long

If proxy deployment is complex, we can **unblock downstream work** by:

1. **Manually create a 480p proxy** of I Am Legend using local ffmpeg
2. **Upload to S3** manually
3. **Register in DB** manually
4. **Start testing audio/VLM stages** immediately

This lets us:
- Test stages 03-06 (audio, VLM, script, TTS) right away
- Come back to proxy automation later
- Maintain forward momentum

---

## My Recommendation

**Start with Option A (Deploy Proxy)** for these reasons:

1. **Validates architecture** — Tests if our RunPod SDK integration actually works
2. **Unblocks everything** — Proxy is the bottleneck for all downstream stages
3. **Proves deployment pattern** — Once proxy works, we know how to deploy the others
4. **Real-world test** — Better than mocks; we'll discover issues early

**Timeline:**
- Investigate current endpoint: 15 min
- Deploy/configure handler: 2-3 hours (or 30 min if Hub worker exists)
- Test end-to-end: 30 min
- **Total: ~3 hours to working proxy**

Then we can:
- Test audio stage (uses proxy)
- Test VLM stage (uses proxy)
- Build confidence in the full pipeline

---

## What Do You Think?

Should we:
1. **Deploy proxy endpoint now** (recommended)
2. **Manually create proxy + test downstream** (faster short-term)
3. **Something else?**

Let me know and I'll start executing immediately.
