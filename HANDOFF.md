# Handoff — Deprecated (RunPod)

**Date:** 2026-08-16 → Deprecated 2026-08-20
**Status:** ❌ Removed — RunPod Serverless and Pod workflows have been deleted.

## What was here

Previous version documented RunPod Serverless timeout issues (10min) and a
Flask Pod workaround for proxy transcoding (`handlers/proxy/pod_server.py`).

## Replacement

All compute now moves to **Modal**:

- `lib/tools/proxy.py` — stubbed for Modal `Function.from_name("splicer", "transcode_proxy")`
- `lib/tools/storage.py` — deprecated; use `modal.Volume` (`splicer-films`)
- `handlers/proxy/` — kept as placeholder, will be removed
- `src/runpod_client.py`, `src/s3.py`, `src/poll_job.py`, `src/stage_*` — stubbed as deprecated

Next step: implement `modal_app/proxy.py` Modal endpoint for 1080p → 480p
using `PyNvVideoCodec` or `ffmpeg` on Modal GPU (`gpu="T4"`/`"L4"`/`"A10G"`),
with `modal.Volume` for film storage and no S3.

See `README.md` and `pyproject.toml` (now `modal>=1.5.4`, no `runpod`/`logfire`).
