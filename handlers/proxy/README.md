# Splicer Proxy Handler — Deprecated

This RunPod handler has been removed. Proxy generation (1080p → 480p)
will be implemented as a Modal endpoint.

See `lib/tools/proxy.py` for the client and `modal_app/` for the server
implementation (coming next).

Previous implementation used PyNvVideoCodec with RunPod Serverless.
All RunPod/Logfire dependencies have been removed.
