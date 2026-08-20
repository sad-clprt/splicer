"""
Deprecated: S3 client for RunPod Network Volumes removed.

Use Modal Volumes instead:
    import modal
    volume = modal.Volume.from_name("splicer-films", create_if_missing=True)
"""

def get_s3_client():
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")

def get_default_bucket() -> str:
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")
