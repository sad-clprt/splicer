"""Modal App and shared resources for Splicer.

Single App "splicer" hosts all pipeline functions (proxy, audio, visual, tts, safety).
Each function can have its own Image/gpu config but shares Volume + Secrets.
"""

import modal

# Shared persistent storage for films — replaces RunPod Network Volume S3
# Mounted at /films in every container
volume = modal.Volume.from_name("splicer-films", create_if_missing=True)
VOLUME_MOUNT = "/films"

# Main App — all functions attach to this
app = modal.App(name="splicer")

# Future: include sub-apps if we split (app.include(proxy_app))
# from .proxy import proxy_app
# app.include(proxy_app)
