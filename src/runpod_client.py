"""Deprecated: RunPod client removed. Use Modal instead.

This file previously wrapped `runpod` SDK for Serverless endpoints.
All RunPod endpoints (proxy, audio, vlm, tts, safety) are being migrated
to Modal Functions. This stub remains to prevent import errors and will be
deleted once src/ legacy pipeline is archived.
"""

def get_endpoint_ids() -> dict[str, str]:
    raise NotImplementedError("RunPod removed. Use Modal Function.from_name() instead.")


class RunPodClient:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("RunPod removed. Use Modal instead.")
