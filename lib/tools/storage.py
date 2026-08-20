"""
Deprecated: S3 storage for RunPod Network Volumes.

RunPod + S3 has been removed in favor of Modal Volumes.
This module is kept as a deprecated shim for reference and will be deleted
once Moto/Modal Volume migration is complete.

For Modal, use `modal.Volume` instead:
    volume = modal.Volume.from_name("splicer-films", create_if_missing=True)
    # in function: @app.function(volumes={"/films": volume})

If you still need S3 for external buckets, use a generic boto3 client
without RunPod-specific defaults.
"""

import os
import pathlib
from typing import Optional


def get_s3_client(*args, **kwargs):
    """Deprecated: RunPod S3 client removed. Use Modal Volumes or generic boto3."""
    raise NotImplementedError(
        "RunPod S3 removed. Use modal.Volume for film storage or create a generic boto3 client. "
        "See lib/tools/storage.py deprecation notice."
    )


def upload_file(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")


def download_file(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")


def list_objects(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")


def delete_object(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")


def object_exists(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")


def get_object_metadata(*args, **kwargs):
    raise NotImplementedError("RunPod S3 removed. Use modal.Volume.")
