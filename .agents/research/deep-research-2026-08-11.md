# Deep Research — Splicer Pipeline Optimization (2026-08-11)

Source: 6 parallel workflows (RunPod MCP live probes + HF `hf models info/card` + `tinyfish_fetch` + Tavily + runpod-docs MCP) as requested. Use this to revise `.agents/plans/2026-08-11-splicer-pipeline.md` before next planning gate.

---

## 1. RunPod Platform — Serverless, Caching, Storage

**Live verification (2026-08-11, `runpod` MCP 54 tools, EU-RO-1):**
- Volume `tn1qxkkw94` `splicer-films` 50 GB `STANDARD` EU-RO-1 `$3.50/mo` (`$0.07/GB/mo`), S3 endpoint `https://s3api-eu-ro-1.runpod.io` bucket = volume ID. High-performance tier unavailable in EU-RO-1 (only `STANDARD`); that is fine — 200–400 MB/s, 10 GB/s peak.
- GPUs: `ADA_24` (RTX 4090 24 GB) `HIGH` global / `MEDIUM` EU-RO-1, `$0.34/hr community` / `$0.74/hr secure`, CUDA 12.2–13.2. Cheapest HIGH-avail 24 GB — primary for all stages. Fallbacks `AMPERE_24` (3090, MEDIUM) or `ADA_32_PRO` (5090) if throttled. S3 ops free, no ingress/egress.
- Zero live endpoints/pods — clean slate. Docs cross-checked via `runpod-docs` MCP.

**Serverless lifecycle:** `Queue → cold start (Initialising, NOT billed: image pull + model download) → Running (billed per-sec, incl. idleTimeout) → Idle → scale-to-0`. `Throttled/Unhealthy` not billed. Types: `QUEUE` (splicer choice, handler `runpod.serverless.start`, `/run`/`/status`, guaranteed retry) vs `LOAD_BALANCER` (no queue, realtime). Knobs: `activeWorkers 0→1` eliminates cold start but 24/7 bill; `maxWorkers 3` default (balance-gated); `idleTimeout 5s`; `executionTimeout 600s`; `scalerType QUEUE_DELAY (wait>4s)` vs `REQUEST_COUNT (ceil((queue+inProgress)/scalerValue))` — set `scalerValue=1` for aggressive fan-out (675 clips → 675 ideal workers, capped). Auto scale-down after 3 d→max 2, 7 d→0. FlashBoot default ENABLED — retains state, seconds revival.

**Model caching — 3 options (docs order: Cached → Baked → Network Volume):**

| Method | Path | Billed during load? | Perf | When |
|---|---|---|---|---|
| **Cached Models (host disk)** | `/runpod-volume/huggingface-cache/hub/models--{org}--{name}/snapshots/{hash}` | NOT billed; RunPod pre-places on host before worker starts | Fastest — seconds even 30B, shared across workers on same host | Any HF public/gated/private model — **preferred for VLM/TTS/Safety** |
| **Docker Layer (bake in)** | `/app/models` in image | Fast after billing starts but image 10–50 GB, slow push/rebuild | Local disk fast | Private non-HF models |
| **Network Volume** | `/runpod-volume/<path>` | BILLED while reading (worker running) | Slowest — network NFS even though same mount as cache, 200–400 MB/s | Dev, 500 GB+ models, or raw film assets |

Implementation: set endpoint `Model` field or `MODEL_NAME` env, handler `HF_HUB_OFFLINE=1`, `local_files_only=True`, `refs/main`. Network volume mount at `/runpod-volume` collides with cache path but cache is host-local vs network — cache still faster per docs. Init outside handler (`model = load()` at module level).

**Storage choice for splicer:** Keep single volume `tn1qxkkw94` as interchange (source_1080p via `app/s3.py` multipart → proxy_480p → VLM decode → final_1080p). S3 API for FastAPI control plane (presigned `init/complete`, `list_objects_v2` verify — HeadObject 403 fallback already in repo). Container disk only for tmp decode. Writing concurrently to same key risks corruption — enforce one-writer per `films/<id>/` prefix. No ingress/egress fees.

**Simpler/efficient architecture:** Single DC EU-RO-1, single image pattern, all Serverless QUEUE, same `ADA_24` pool across stages but separate endpoints for isolation/scaling (concurrency 3 dev → 30 prod, Neon `pool_size=20`). Serverless beats Pods for pipeline: bursty, queue-retry, scale-to-zero, per-sec billing cheaper than pod per-min idle. Use Pods only for interactive debug (Blender manual preview, VLM prompt tuning) with volume at `/workspace`. Multi-DC second volume only if 4090 MEDIUM throttles — then attach both volumes but S3-sync data manually (no auto sync), constrains scheduler.

Verification: `list-network-volumes`, `list-data-centers`, `list-gpu-types`, `get-gpu-type`, `get-capacity`, `list-endpoints/pods`, `get-billing` — see `.agents/research/runpod-optimization.md` (134 lines, 15 KB) for full probes.

---

## 2. Models Research

### Qwen3-VL-8B-Instruct — `Qwen/Qwen3-VL-8B-Instruct` (8.77 B BF16, 17.5 GB storage, Apache-2.0, 4.5 M downloads, 1040 likes, 2025-10-11)

Verified: `Qwen3VLForConditionalGeneration` (`model_type qwen3_vl`), `AutoModelForMultimodalLM`, processor `AutoProcessor`. Tags: `endpoints_compatible`, `image-text-to-text`.

**Key for splicer:**
- Native **256K** context, expandable 1M, `Interleaved-MRoPE` (time/width/height pos), `DeepStack` (multi-level ViT fusion), `Text–Timestamp Alignment` — enables hour-long video second-level indexing.
- Architecture: ViT deep features fused, timestamp-grounded event localization > T-RoPE.
- Recommended: `flash_attention_2`, `dtype bfloat16`, `device_map auto`, `transformers` built from source (4.57 pending). Generation defaults: VL `top_p 0.8 top_k 20 temp 0.7 presence 1.5 out 16384`; text variant similar.
- Vision: `patch16 merge2 32×` no tiling, per-frame tokens configurable — repo plan 128 tok @ 362×362 vs 256 tok @ 512×512 (2× cost). Paper/specs confirm 128 tok sufficient for grounding while halving VRAM — use 128 default, 256 escalate path only if grounding low.
- Fits RTX 4090 24 GB with vLLM `max_num_seqs 64`, 8-frame batches → 675 clips × 8 = 5400 frames @ 1 FPS (90 min × 24 FPS would be 129k, reduced correctly per handoff).
- Output target Stage1 per 8-frame clip: `{chars, actions, importance}` JSON — feed Stage2 per-scene fuse (+ SRT + diarization + KB) → Stage3 beats → OpenRouter stronger LLM (Qwen-VL text understanding on par with pure LLM but stronger model preferred for narrative).

Install: `pip install git+https://github.com/huggingface/transformers` + `flash-attn`.

### Shieldstral-1.0-3B — `mistralai/Shieldstral-1.0-3B` (3.84 B BF16, 15.4 GB storage, Apache-2.0, Ministral-3B + Pixtral, vLLM/sglang/transformers/llama.cpp)

Base `Ministral-3-3B-Base-2512`, arch `Mistral3ForConditionalGeneration` (`mistral3`), tokenizer `tekken`. 32K training context (256K theoretical). Multilingual 12 langs.

**Key for splicer:**
- Policy-adaptive — natural-language policy at inference time, single forward pass, single-token `yes`/`no` with continuous score (softmax over `yes`/`no` logits, threshold 0.5, multilabel via one query per policy). System: `Judge whether the Document meets requirements based on Query and Instruction — answer only yes/no`.
- Modes: text-only, image-only, text+image sandwich `[<Instruct><Query><Document> prefix, image, trailing caption]`. For splicer: multimodal per-frame (1 FPS final only, 840–1200 frames @ 14–20 min), query `Does this content contain blood/extreme violence/nudity?` + instruct strict/moderate. Returns `score, flagged`.
- **Why final only:** 840–1200 forward passes vs 5400 (source 90 min) or 129k (24 FPS) — cost 4.5×–100× saving. Low tolerance for montage.
- Runs single GPU BF16 16 GB (fits ADA_24 cheaply) via `vllm serve mistralai/Shieldstral-1.0-3B --max-model-len 32768`. Score extraction requires `logprobs=True top_logprobs=20` (vLLM) or hidden-state softmax (transformers) — map to `[{t0,t1,x,y,w,h,reason,score}]`. Use to drive Blender blur/mask rectangles, not just timestamp.

### WhisperX — `m-bain/whisperX` (23.5k★, BSD-2-Clause, v3.8.7rc1, Python `>=3.10,<3.14` — note splicer pins `3.14.2`, risk)

Paper `arXiv:2303.00747` (INTERSPEECH 2023). Architecture: `VAD cut & merge → batched faster-whisper (CTranslate2, 70× realtime large-v2) → wav2vec2 forced alignment (word-level, phoneme) → pyannote diarization`.

**Key for splicer:**
- Fixes Whisper utterance-level timestamps (seconds error) → word-level via wav2vec2 (`WAV2VEC2_ASR_LARGE_LV60K_960H` en, auto picks per lang via `torchaudio`/`HF` `DEFAULT_ALIGN_MODELS_HF` — test for non-en). Also VAD reduces hallucination, enables batching (`without_timestamps True`, `condition_on_prev_text False`).
- **Phase usage:** SRT primary (50 KB exists) — WhisperX only gap-fills where SRT missing; extract 16k mono via ffmpeg, `whisperx.load_model("large-v2", device, compute_type float16/int8) → transcribe → load_align_model → align → DiarizationPipeline(hf_token, pyannote/speaker-diarization-community-1) → assign_word_speakers`. Fusion `enrich_scene` per PySceneDetect cut (with librosa RMS).
- **Post-TTS captions:** Run WhisperX again on final TTS wav to get precise word timings for edit driving (cut/hold single frame longer) — output `[{word,start,end,speaker}]` to align script ↔ final video for fair-use pacing. This closes the loop user described.
- Constraints: overlapping speech poor, numbers/money unaligned, diarization imperfect — document gaps. GPU <8 GB large-v2 beam5, batch_size 16; int8 for low mem.

Simpler alternative: if alignment overhead heavy, use `faster-whisper` directly + manual alignment, but WhisperX batch + VAD gives best speed/accuracy trade-off.

---

## 3. Final Video Export — RunPod Serverless + PyNvVideoCodec + Blender Headless

**TL;DR recommendation:** Do not ship `.blend` via JSON payload (~20 MB limit). Build timeline on worker from JSON EDL.

Flow:
```
FastAPI/Inngest → (1) generate edit_decision.json (scenes, timestamps, markers, safety blurs, script beats)
                → (2) PUT to volume S3 `s3://tn1qxkkw94/films/<id>/edit_decision.json`
                → (3) runpod.run({"input": {"film_id","edit_json_s3_key","original_s3_key"}})
                → worker mounts /runpod-volume, fetches original 1080p, applies edits, NVENC exports final_1080p + thumbnail
                → (4) S3 ls verify, Neon assets(status=available, kind=final_1080p)
```

**Proxy/original sync:** Both must share FPS, timebase, GOP. Source `I.Am.Legend...mp4` detected fps is 23.976 or 24 — set Blender `scene.render.fps / fps_base` to match source before any strip insert. Proxy `scale=854:480 h264_nvenc -g 30` matches source GOP30; final export same GOP, same fps, 1920×1080, no fps conversion else drift. Validate `ffprobe -show_streams` on both before `bpy`.

**Blender headless VSE:** `blender --background --python assemble.py -- <args>` or `bpy` headless (requires `libgl`). API: `bpy.context.scene.sequence_editor_create()`, `sequencer.sequences.new_movie(name, filepath, channel, frame_start)`, `new_sound`, `new_effect("TRANSFORM"/"GAUSSIAN_BLUR")` for blur regions, `bpy.ops.sequencer.view_all()`. Use headless Serverless image `blender:4.2 + ffmpeg + pynvvideocodec + bpy`. RunPod volume at `/runpod-volume` → translate S3 key to path. Do not assume `/workspace` (pod) vs `/runpod-volume` (serverless).

**Structured payload (clean, well-documented):**

```json
{
  "film_id": "945c6475-a629-4140-9968-9135d716565d",
  "fps": 24,
  "proxy_s3_key": "films/945c.../480p_proxy.mp4",
  "original_s3_key": "films/945c.../I.Am.Legend.1080p.mp4",
  "edit_version": "v1",
  "scenes": [
    {"id":0, "start_sec":0.0, "end_sec":12.34, "src_start_sec":0.0, "src_end_sec":12.34, "importance":0.9, "chars":["Robert Neville"], "action":"driving empty streets", "script_segment_id":"seg_001"}
  ],
  "markers": [
    {"time_sec":45.2, "type":"scene_cut", "label":"Act1 inciting"},
    {"time_sec":120.5, "type":"safety", "label":"blood blur region", "fix":"blur", "bbox":{"x":0.32,"y":0.45,"w":0.18,"h":0.22}}
  ],
  "safety_flags": [
    {"t0":123.4,"t1":125.1,"category":"blood","score":0.87,"fix":"gaussian_blur","bbox":{"x":0.1,"y":0.2,"w":0.3,"h":0.25},"reason":"extreme violence"}
  ],
  "script": {"text":"Voiceover ...","segments":[{"id":"seg_001","text":"...","tts_s3_key":"films/.../tts_seg001.wav","start_sec":0,"duration_sec":8.2}]},
  "export": {
    "width":1920,"height":1080,"fps":24,"gop":30,
    "video_codec":"h264_nvenc","preset":"slow","rc":"vbr_hq","cq":23,"bitrate_kbps":8000,"maxrate_kbps":12000,
    "audio_codec":"aac","audio_bitrate_kbps":384,"pix_fmt":"yuv420p",
    "container":"mp4","profile":"high","level":"4.2"
  }
}
```

Marker types: `scene_cut`, `safety`, `cut_hold`, `blur`, `subtitle`. User edits polished `480p_proxy` timeline in Blender VSE locally with this JSON imported as markers (`bpy.ops.marker.add()` + `frame = time_sec*fps`). Final .blend passed to `bpy` script which reads JSON markers, not `.blend` binary.

**Blender operations for safety:** `sequence_editor.sequences.new_effect("GAUSSIAN_BLUR")` masked to `bbox` for flagged intervals; or `new_mask` + `use_animated`. Alternative `ffmpeg -vf "delogo"` or `boxblur` at same timestamps — simpler headless but marker JSON still drives it. PyNvVideoCodec `nvc.PyNvEncoder` for pure transcode, `bpy` for composition + NVENC mix.

**WhisperX on final TTS:** After TTS, `whisperx final_tts.wav → {words:[{word,start,end}]} → build EDL pacing: cuts where TTS pause >0.5s, hold single frame where script beat needs emphasis — aligns final video to narration for fair-use transformative edit.

**YouTube 1080p best export (support.google.com/youtube/answer/1722171 via docs search):**
- Container MP4, Video H.264 High Profile, 8 Mbps (standard) 12 Mbps (high motion), `1920×1080`, fps original (24/30), `8-bit 4:2:0`, closed GOP 30 (half-sec at 60, 1-sec at 30 — match source 30), Audio AAC-LC 384 kbps 48 kHz stereo. For RunPod `ffmpeg -c:v h264_nvenc -rc vbr_hq -cq 23 -b:v 8M -maxrate 12M -profile:v high -g 30 -c:a aac -b:a 384k -pix_fmt yuv420p`.
- Do not re-encode proxy — only final 1080p from original via volume.

---

## 4. YouTube Guidelines — Monetization for Movie Recap Channels

**YPP (support.google.com/answer/13429240 + Tavily):** prerequisites + “inauthentic content” (2025-07-15 rename from repetitious) vs **reused content** (commentary/clips/compilations/reactions) reviewed separately — reused policy unchanged. Violations remove monetization entire channel if indistinguishable.

**Allowed to monetize (reused):**
- Clips for critical review; scene where you rewrote dialog + changed voiceover — *core splicer pattern*.
- Edited footage + storyline + commentary; replays explaining moves; audio/visual effects demonstrating substantive editing + unique to channel.
- Content where uploader visible or explains how they added value.

**Not allowed (reused violation):**
- Clips from favorite show stitched with little/no narrative.
- Shorts compiled from other socials, song collections even with permission, minimal changes (permission ≠ reused pass; separate from copyright).

**Monetization techniques to stay fair & monetized (extracted from FAQ + Community Guidelines):**

1. **Transformative voiceover mandatory:** No original audio/music — voiceover-only fulfills `meaningful difference` test (rewritten dialog + original TTS). Support doc `Reused content ... allowed: scene where you’ve rewritten dialog and changed voiceover`.
2. **No full-scene playback:** Use sub-10s clips, cut every 3–5s, never continuous 30s+ — reduces Content ID; hold single frame longer where narration needs emphasis + fair-use pacing (via WhisperX TTS word timings).
3. **Add substantive narrative arc, not generic templated recaps:** Each video distinct storyline/focus — per `Inauthentic` policy substance must be varied. Build Stage3 beats → script with critique/education (why scene matters).
4. **Cohesive script:** Support doc `cchannels need cohesive narrative, not disturbing themes without arc` — script via stronger LLM with act structure avoids “repetitive scenarios”.
5. **Visual differentiation:** Audio/visual effects unique to channel, substantive editing. Blender markers document every edit — reviewers see intentional transformation.
6. **Blood/violence/nudity handling (Community Guidelines violent/graphic, nudity/sexual):**
   - Allowed: blurred/censored, educational context allowed but advertiser-friendly needs blur; video must not intend to shock — educational recaps with blur pass.
   - Not advertiser-friendly: unblurred gore/extreme violence first 8–30s, explicit nudity. Per `answer/9288567`: violent gory to shock not allowed; sex/nudity keeps safe threshold.
   - Technique: Shieldstral single-quantum flags → `bbox` blur via `GAUSSIAN_BLUR` mask, crop, or `boxblur` at `t0-t1`; keep blur margin 10% to avoid leakage. Document each as `safety` marker with `fix` and `score` for audit. Preserve narrative after blur (audio continues).
7. **Thumbnail:** No sensational gore/nudity even blurred — Community Guideline thumbs separate.
8. **Video specs:** 14–20 min (720–1200s) > reused threshold of compilations; holds watch time but not mass-produced feel. Original channel face or explain-value segment optional but strengthens `reused` pass.
9. **Disclose AI:** If GenAI face/voice synthesis shown as real, disclose per `answer/14328491` (not needed for voiceover-only).
10. **Channel-level check:** Reviewers check videos, descriptions, thumbs, Shorts — keep all recap descriptions with source credit + transformative statement (`This video provides original commentary and analysis for educational purposes under fair use (17 U.S.C. §107)`).

**Risk:** Content ID still may claim even if reused passes — prepare dispute with fair-use four factors (purpose transformative voiceover, nature published film, amount minimal clips, market no replacement). Monetization may be limited (yellow icon) after auto-review up to 24h + human — per `answer/16271309`.

---

## 5. Simpler/Efficient Implementation Findings

- **Do not split into many GPU endpoints if cost-capped:** Single `ADA_24` pool + queue suffices; multiple endpoints (proxy, VLM, TTS, safety, assemble) still share same GPU type — just logically separate for scaling but can collapse to one `splicer` endpoint with `task` param if you want simplest. Separate recommended for isolation (VLM 675 fan-out needs REQUEST_COUNT, proxy needs QUEUE_DELAY) but not required.
- **RunPod public endpoints:** `list-public-endpoints` shows managed models — not needed, slower.
- **High-perf volume:** Not needed until 10 GB+ throughput bottleneck.
- **Caching vs network volume:** Already simplest — cached models for HF, network volume only for film assets.

Ready to revise plan with these inputs.
