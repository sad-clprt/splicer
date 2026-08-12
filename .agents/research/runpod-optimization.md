# RunPod Research — Splicer Pipeline Optimization

**Date:** 2026-08-11 | **Probed:** `runpod` stdio (54 tools, v3.2.0 v2 REST), `runpod-docs` HTTP (https://docs.runpod.io/mcp) | **Volume verified:** `tn1qxkkw94` splicer-films 50GB STANDARD EU-RO-1 ($3.50/mo)

## 1) Serverless Endpoint Lifecycle & Cold Starts

**Lifecycle** (`/serverless/overview`, `/serverless/workers/overview`):
```
Request → Queue → Check worker ready? —No→ Cold Start (start container, pull image, init runtime, load model → GPU)
                                —Yes→ Handler → /status or /runsync result
Idle workers: stay warm `idleTimeout` (default 5s, 1-3600s, billed while warm) then scale to 0.
```
Worker states (`/serverless/workers/overview`): `Initializing` (image + cached-model download, **NOT billed**), `Running` (billed), `Idle` (scaled-down, not billed), `Throttled` (host constraint, not billed), `Outdated` (billed while finishing), `Unhealthy` (crashed, auto-retry 7d).

**Endpoint types:** `QUEUE` (managed queue, /run /runsync /status, guaranteed + retry, handler function `runpod.serverless.start({"handler":...})`) vs `LOAD_BALANCER` (direct HTTP to worker FastAPI/Flask, no queue, `REQUEST_COUNT` only, for realtime APIs). Splicer needs **QUEUE**.

**Key knobs** (`/serverless/endpoints/endpoint-configurations`):
- `activeWorkers` 0 default = scale-to-zero; 1+ always-warm eliminates cold start but billed 24/7.
- `maxWorkers` default 3 (account balance gates total flex+active: $0 5, $100 10 … $900 60).
- `idleTimeout` 5s default; auto-scale-down unused endpoint after 3d→max 2 (email), 7d→max 0.
- `executionTimeout` 600s default (5s–7d), `TTL` 24h, `retention` async 30m / sync 1m.
- `scalerType`: `QUEUE_DELAY` (add worker if wait >4s, higher utilization) vs `REQUEST_COUNT` (`ceil((queue+inProgress)/scalerValue)`, scalerValue 4 default, **1 = max responsiveness**, recommended for LLM/short jobs).
- `dataCenterIds`: restrict; fewer = less availability.
- `allowedCudaVersions`: pick required + newer (backward compat) — widens pool (`get-capacity` matrix).

**Cold-start optimization (verified via `search_runpod_documentation` + docs):**
1. **Cached models** (best) — see §1b. Seconds even for large models, no download billing.
2. **FlashBoot** — retains worker state after spin-down, faster revival than fresh boot; default **ENABLED** on new GPU/CPU endpoints; effective when workers cycle frequently. `OFF|FLASHBOOT|PRIORITY_FLASHBOOT`.
3. **Optimize image** — smaller base, remove deps; Docker layer caches on container disk (local NVMe) but **model load to GPU still dominates**.
4. **Init outside handler** — `model = load()` at module level, handler only `predict`; avoids per-request reload.
5. **activeWorkers=1** for prod latency-sensitive path (cost tradeoff).

**Model Caching — 3 options** (`/serverless/workers/overview`, `/serverless/endpoints/model-caching`, `/tutorials/serverless/model-caching-text`):

| Method | Path | When billed? | Perf | Use case |
|--------|------|--------------|------|----------|
| **1. Cached Models (host disk)** | `/runpod-volume/huggingface-cache/hub/models--{org}--{name}/snapshots/{hash}` | **NOT billed** during download; RunPod pre-places on host before worker starts, tries cached host first else waits (unbilled) | **Fastest**: shared across workers on same host, “seconds” even 30B; faster than network volume despite same `/runpod-volume` mount (host-local vs NFS) | Any HF public/gated/private model — **preferred**. Set endpoint **Model** field or `MODEL_NAME` env, handler `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `local_files_only=True`, `resolve_snapshot_path()` via `refs/main`. |
| **2. Docker Layer (bake in)** | baked `/app/models` in image | Container disk local, fast after billing starts | Fast (machine disk), but image 10-50GB pushes slower, rebuild on model change | Private non-HF models not on Hub. Increases cold start vs cached but still local disk. |
| **3. Network Volume** | `/runpod-volume/<path>` | **BILLED** while reading (worker running) | Slowest: 200-400 MB/s network (10GB/s peak) vs local; “worker init faster but model load slower, billed” | Dev or 500GB+ huge models, or custom datasets. Convenient iteration (no rebuild) but billed load. |

Docs priority order: **Cached → Baked → Network Volume**. For splicer: VLM/TTS/Safety are HF → **Cached**; proxy Blender assets → baked FFmpeg+Blender + runtime volume reads.

## 2) Storage Options

| Option | Scope | Mount | Perf | Pricing (EU-RO-1 verified) | Notes |
|--------|-------|-------|------|----------------------------|-------|
| **Network Volume STANDARD** | Independent of compute, persists across pods/serverless | Serverless `/runpod-volume`, Pods `/workspace` (replaces volume disk) | NVMe SSD 200-400 MB/s, up to 10 GB/s peak (High-perf 3× thr 4× IOPS) | **$0.07/GB/mo first TB, $0.05 beyond** → `tn1qxkkw94` 50GB = **$3.50/mo** (billing API confirms $0.014/d then $0.106/d partial). No ingress/egress fees. | Single volume per DC; multi-volume attachment improves availability (workers distributed, exactly one volume per worker) but **data does not sync** — manual copy via S3. Writing concurrent from multiple workers risks corruption. Only Secure Cloud pods. Must attach at creation. |
| **Network Volume HIGH_PERFORMANCE** | Same | Same | 3× thr 4× IOPS parallel | Premium (console shows delta) | Available only select DCs (EU-FR-1, EUR-NO-2, US-CA-2 etc). **EU-RO-1 only STANDARD** (see `list-data-centers`: EU-RO-1 `["STANDARD"]`). |
| **S3-compatible API** (same volume) | Zero-compute access | `s3://<VOLUME_ID>/path` maps to `/workspace/...` or `/runpod-volume/...` | Network-limited; ls on 10k+ files/10GB+ slow | **Same billing** as volume (no extra); S3 ops free | Per-DC endpoint `https://s3api-eu-ro-1.runpod.io` (EU-RO-1), needs separate S3 key `user_...`/`rps_...` (not `rpa_...`). Supports `aws s3 ls/cp/rm/sync`, `boto3` (`app/s3.py` uses `s3v4`, `AWS_MAX_ATTEMPTS=10`). Presigned 401 + HeadObject 403 fallbacks verified → keep `list_objects_v2`. |
| **Pod Volume Disk** | Pod lease only | `/workspace` | Local disk, fast | Included in pod min billing; sized at deploy | Not portable. Deleted with pod (unless network volume). |
| **Container Disk** | Ephemeral worker/pod | `/` overlay | Local fastest | Included (bill while running) | Lost on scale-down/stop. Default handler scratch; must copy to volume to persist. |

**tn1qxkkw94 detail** (live probe `get-network-volume`): `id tn1qxkkw94, name splicer-films, size 50, type STANDARD, dataCenter EU-RO-1`. `EU-RO-1` (`get-data-center`): `region EUROPE, compliance GDPR+HIPAA, globalNetwork true, networkVolumeTypes ["STANDARD"]`, S3 endpoint `https://s3api-eu-ro-1.runpod.io`. `app/s3.py` already points there; bucket = volume ID.

**Decision:** Keep **Network Volume** as pipeline interchange (source_1080p via `app/s3.py` multipart → proxy_480p → VLM frames can be decoded on GPU from mounted `/runpod-volume` or streamed via S3; final 1080p back to volume). Use **S3 API** for FastAPI control plane (presigned multipart `init/complete`, `list_objects_v2` verify) without launching pods. **Container disk** only for worker tmp decode.

## 3) GPU Types, Concurrency, Scaling

**Live probe `list-gpu-types` + `get-gpu-type` + `get-capacity`:**

| GPU | Pool | VRAM | Secure | Community | Avail global | Avail EU-RO-1 | CUDA | Use |
|-----|------|------|--------|-----------|--------------|---------------|------|-----|
| **RTX 4090** ADA_24 | `ADA_24` | 24GB | $0.74/hr $0.00021/s | **$0.34/hr $0.000094/s** | **HIGH** (top) | **MEDIUM** | 12.2-13.2 AVAILABLE | Splicer primary |
| RTX 5090 | `ADA_32_PRO` | 32GB | $0.99 | $0.69 | HIGH | — | — | Headroom for VLM batch ↑ |
| RTX 3090 | `AMPERE_24` | 24GB | $0.50 | $0.22 | MEDIUM | — | — | Cheaper but Ampere slower, fewer NVDEC tricks |
| L4 | `AMPERE_24` | 24GB | $0.49 | $0.44 | LOW | — | — | Inference-optimized |
| L40S | `ADA_48_PRO` | 48GB | $0.99 | $0.79 | LOW | — | — | 48GB need |
| 6000 Ada | `ADA_48_PRO` | 48GB | $0.84 | $0.74 | LOW | — | — | 48GB need |
| A100 SXM4 | `AMPERE_80` | 80GB | $1.59 | $1.39 | MEDIUM | — | — | 80GB big LLM |
| H100 SXM | `ADA_80_PRO` | 80GB | $3.29 | $2.69 | HIGH | — | — | Huge models |
| H200 | `HOPPER_141` | 141GB | $4.59 | $3.59 | MEDIUM | — | — | Extreme |

Prices = on-demand per hr; RunPod bills **per second** when worker Running (including idleTimeout warm). Catalog 47 types sorted by availability.

**Concurrency/scaling** (`endpoint-configurations`):
- 3 scaling signals: `workersMin/max`, `idleTimeout`, `scalerType/Value`.
- `QUEUE_DELAY` vs `REQUEST_COUNT` — for splicer batch 675 clips, `REQUEST_COUNT` with `scalerValue=1` gives `ceil(675/1)=675` ideal workers (capped by `maxWorkers`) → max parallelism; `QUEUE_DELAY` would throttle to wait >4s.
- Account max workers balance-gated; `maxWorkers` is cost cap. Set `workersMax ~20% above expected concurrency` for spikes.
- Serverless GPU pool allows fallback list: e.g., `gpuIds "ADA_24,AMPERE_24"` with exclusions `"-NVIDIA RTX 2000 Ada"` to avoid slow pool members.
- EU-RO-1 constraint: `ADA_24` MEDIUM means available but limiting — fallback to `EU-CZ-1 LOW`, `EUR-IS-1 LOW`, `EUR-NO-1 LOW` or US pools if you attach multi-DC volumes (see below).

**Recommendation for splicer:** Stay **ADA_24 (RTX 4090)** across all Serverless endpoints — cheapest HIGH-avail 24GB, 2× NVDEC (2 threads), GOP30 1072 FPS proxy advantage, fits Qwen3-VL-8B (24GB with vLLM `max_num_seqs 64`, 8-frame×128tok=1024 tok/batch) + TTS 1.7B + Shieldstral 3B single pass. Alternatives only if 4090 throttled at EU-RO-1: secondary pool `AMPERE_24` (3090) or `ADA_32_PRO` (5090) as fallback list. Use **Secure Cloud** for prod ($0.74) if reliability > cost; **Community** ($0.34) for dev to halve proxy cost.

## 4) Recommendation Per Pipeline Stage — Simplest/Efficient Architecture

**Principle:** FastAPI Cloud (no GPU) + Inngest durable orchestration → **queue-based Serverless** everywhere (no pods) except one-off debug Pod. Single DC EU-RO-1, single volume `tn1qxkkw94`, single image pattern.

```
FastAPI Cloud (Neon, Logfire, Inngest)
  | Inngest film/proxy.requested, scene_detect, vlm, tts, safety (concurrency 3 dev →30 prod)
  v
[ S3 API https://s3api-eu-ro-1.runpod.io  s3://tn1qxkkw94/films/<id>/ ]  ← FastAPI + volume share
  |
  ├─► Endpoint `splicer-proxy`  ADA_24, 0→3 workers, 20GB disk, FlashBoot ON, idle 5s, QUEUE_DELAY 4, volume tn1qxkkw94
  │     Image: python+ffmpeg+pynvvideocodec (1072 FPS) or ffmpeg hwaccel cuda scale=854:480 h264_nvenc -g 30
  │     Input /runpod-volume/films/<id>/1080p.mp4 → /runpod-volume/films/<id>/480p_proxy.mp4  (S3 ls verify)
  │     ➜ Simple, billed per-sec only while transcoding; Pod fallback identical ffmpeg but needs manual start/stop.
  │
  ├─► Endpoint `splicer-vlm`  ADA_24, 1→6 workers, Cached Model Qwen3-VL-8B-Instruct, vLLM max_num_seqs 64
  │     Handler: 1 FPS NVDEC (2 threads) device-mem resize 362×362 128 tok → 8-frame batches → Stage1 JSON per 675 clips
  │     Stage2 fuse per PySceneDetect scene (+ SRT + pyannote + KB from films.metadata)
  │     Stage3 beats → S3 films/<id>/vlm/{stage1,2,3}.json + Neon jobs mirror
  │     scaler REQUEST_COUNT value 1 (aggressive fan-out via Inngest step.parallel batch 32), FlashBoot ON, active 0 dev /1 prod
  │     ➜ Serverless>Pod: queue guarantees 675 retries, scale-to-zero cheap, cached model = seconds cold start (vs network volume billed slow). Pod only for interactive prompt tuning.
  │
  ├─► Endpoint `splicer-tts`  ADA_24, 0→2 workers, Cached Model Qwen3-TTS-12Hz-1.7B-CustomVoice
  │     Input: script (OpenRouter stronger model, 2100-3000w) + SRT timing → wav
  │     ➜ Single job per film, Serverless fine; load FAST via cache, not network volume.
  │
  ├─► Endpoint `splicer-safety`  ADA_24, 0→2 workers, Cached Model Shieldstral-1.0-3B
  │     Runs ONLY on final 14-20m (840-1200 frames @1 FPS, single forward pass policy-adaptive) → flags json → blur mask re-encode
  │     Could be CPU (3B small) but GPU same ADA_24 simplifies pool & low per-sec cost; Serverless avoids pod idle.
  │
  └─► Endpoint `splicer-assemble`  ADA_24, 0→2 workers, Image blender+ffmpeg+NVENC
        Bpy markers scenes/safety + TTS wav + proxy/1080p cuts → NVENC h264 1920×1080 final_1080p + thumbnail → volume
        ➜ Serverless works (container disk for tmp render, output to /runpod-volume). Pod alternative useful for manual Blender preview (mount volume at /workspace, SSH), but pipeline wants queue + retry so Serverless is simpler.
```

**Serverless vs Pods rule:**
- **Use Serverless when:** bursty, queue-retry, auto-scale, scale-to-zero cost matters (all splicer stages: proxy parallel 3, VLM 675 fan-out, TTS/safety single, assemble). Billing per-sec + not-billed init is cheaper than pod per-min with idle waste. Attach network volume only when persistence needed.
- **Use Pods when:** long interactive debug (Blender manual, VLM prompt iteration), or need persistent volume disk > network latency, or custom TCP/SSH. Not for pipeline fan-out.

**Simplest arch** (what to build next per `HANDOFF.md §8` + plan Phase 1):
1. `splicer-proxy` Serverless `ADA_24` 0→3, volume `tn1qxkkw94`, image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` + `ffmpeg pynvvideocodec scenedetect`, FlashBoot enabled, `executionTimeout 600s`. Reuse `app/s3.py` head/list fallbacks.
2. Keep `tn1qxkkw94` STANDARD (no migration to HIGH_PERF; EU-RO-1 lacks it, not bottleneck yet). Pre-populate via S3 API (already).
3. VLM/TTS/safety all **same GPU pool ADA_24**, separate endpoints for isolation/scaling, all **Cached Models** (not network volume). That avoids network volume DC constraint on model load.
4. Multi-DC: **do not** add second volume until availability blocks. If 4090 MEDIUM at EU-RO-1 throttles, add second STANDARD volume at EU-CZ-1 or EUR-IS-1 + attach both to endpoints → workers distributed, but then must S3-sync data (no auto sync).
5. FastAPI keeps Inngest `concurrency=[3]` dev (raise pool_size 20 when tuning to 30), Logfire `if-token-present`.

**Risks:** Volume constrains endpoint to EU-RO-1 (reduces pool) — mitigated by cached models + community pool. Concurrent write corruption — enforce one-writer per film key. Balance $0 → volume terminated — enable low-balance notifications.

**Verification:** Live probes 2026-08-11: `list-network-volumes` → tn1qxkkw94 ok, `list-data-centers` → EU-RO-1 STANDARD only, `list-gpu-types 4090` → HIGH ($0.34/$0.74), `get-gpu-type 4090` → EU-RO-1 MEDIUM vs EU-CZ-1 LOW, `get-capacity 4090` → CUDA 12.2-13.2 AVAILABLE, `list-endpoints/pods` → 0 live (clean), `get-billing` 30d storage $0.121 (50GB prorated).

Refs: `/serverless/overview`, `/serverless/endpoints/endpoint-configurations`, `/serverless/endpoints/model-caching`, `/serverless/workers/overview`, `/storage/network-volumes`, `/storage/s3-api`, `/storage/high-performance-storage`, `/pods/overview`.
