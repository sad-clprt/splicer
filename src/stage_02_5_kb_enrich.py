"""Deprecated: S3-based KB enrich removed. Will be reimplemented with Modal Volumes."""
def fetch_tmdb_data(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use Modal Volume.")
def fetch_omdb_data(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use Modal Volume.")
def kb_enrich(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use Modal Volume.")
