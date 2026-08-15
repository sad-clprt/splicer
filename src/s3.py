"""S3 client configuration for Splicer storage.

This module provides the base S3 client configuration used across the application.
For actual S3 operations (upload, download, etc.), use lib/tools/storage.py instead.
"""

import os
import boto3
from botocore.client import Config


def get_s3_client():
    """Get configured S3 client for Runpod network volume.

    Returns boto3 S3 client configured with Runpod credentials from environment.

    Environment variables:
        AWS_S3_ENDPOINT: S3 endpoint URL (default: https://s3api-eu-ro-1.runpod.io)
        AWS_S3_REGION: AWS region (default: EU-RO-1)
        AWS_ACCESS_KEY_ID: AWS access key
        AWS_SECRET_ACCESS_KEY: AWS secret key
        RUNPOD_VOLUME_ID: Default bucket name for network volume
    """
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"),
        region_name=os.getenv("AWS_S3_REGION", "EU-RO-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
    )


def get_default_bucket() -> str:
    """Get the default S3 bucket name from environment.

    Returns:
        The RUNPOD_VOLUME_ID environment variable value

    Raises:
        ValueError: If RUNPOD_VOLUME_ID is not set
    """
    bucket = os.getenv("RUNPOD_VOLUME_ID")
    if not bucket:
        raise ValueError("RUNPOD_VOLUME_ID environment variable must be set")
    return bucket
