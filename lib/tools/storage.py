"""S3 storage operations for Runpod network volumes and external buckets."""

import os
import pathlib
from typing import Optional

import boto3
from botocore.exceptions import ClientError


def get_s3_client(use_api_key: bool = False):
    """Get configured S3 client for Runpod network volume.

    Supports two credential modes:
    1. Internal (default): Uses AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY
       - Works only from within Runpod infrastructure (serverless workers, pods)
    2. External: Uses S3_ACESS_KEY/S3_SECRET_ACCESS_KEY
       - Works from external environments (local machine, CI/CD)
       - Requires S3 API key created in Runpod console Settings

    Args:
        use_api_key: If True, use S3 API key credentials for external access.
                    If False (default), use endpoint environment variables.
                    Auto-detects and falls back if credentials are missing.

    Returns:
        boto3 S3 client configured with Runpod credentials.
    """
    # Determine which credentials to use
    if use_api_key:
        # External S3 API key credentials
        access_key = os.getenv("S3_ACESS_KEY")
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            # Fallback to internal credentials if API key not available
            access_key = os.getenv("AWS_ACCESS_KEY_ID")
            secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    else:
        # Internal endpoint credentials (default)
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        # Fallback to S3 API key if internal credentials not available
        if not access_key or not secret_key:
            access_key = os.getenv("S3_ACESS_KEY")
            secret_key = os.getenv("S3_SECRET_ACCESS_KEY")

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"),
        region_name=os.getenv("AWS_S3_REGION", "EU-RO-1"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_file(
    local_path: str,
    s3_key: str,
    bucket: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Upload a file to S3.

    Args:
        local_path: Path to local file to upload
        s3_key: S3 object key (path within bucket)
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)
        metadata: Optional metadata dict to attach to object

    Returns:
        Dict with upload results including size_bytes and s3_uri

    Raises:
        FileNotFoundError: If local file doesn't exist
        ClientError: If S3 upload fails
    """
    local_file = pathlib.Path(local_path)
    if not local_file.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client()
    size_bytes = local_file.stat().st_size

    extra_args = {}
    if metadata:
        extra_args["Metadata"] = metadata

    try:
        s3_client.upload_file(str(local_file), bucket, s3_key, ExtraArgs=extra_args if extra_args else None)

        return {
            "bucket": bucket,
            "key": s3_key,
            "size_bytes": size_bytes,
            "size_mb": size_bytes / (1024 * 1024),
            "s3_uri": f"s3://{bucket}/{s3_key}",
        }
    except ClientError as e:
        raise ClientError(
            {
                "Error": {
                    "Code": e.response["Error"]["Code"],
                    "Message": f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {e.response['Error']['Message']}",
                }
            },
            "upload_file",
        )


def download_file(
    s3_key: str,
    local_path: str,
    bucket: Optional[str] = None,
    use_api_key: bool = False,
) -> dict:
    """Download a file from S3.

    Args:
        s3_key: S3 object key to download
        local_path: Local path to save file to
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)
        use_api_key: If True, use S3 API key for external access

    Returns:
        Dict with download results including size_bytes

    Raises:
        ClientError: If S3 download fails
    """
    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client(use_api_key=use_api_key)

    # Ensure parent directory exists
    pathlib.Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        # Use get_object for better compatibility with S3 API keys
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        
        # Write file manually
        with open(local_path, "wb") as f:
            f.write(response["Body"].read())

        size_bytes = pathlib.Path(local_path).stat().st_size

        return {
            "bucket": bucket,
            "key": s3_key,
            "local_path": local_path,
            "size_bytes": size_bytes,
            "size_mb": size_bytes / (1024 * 1024),
        }
    except ClientError as e:
        raise ClientError(
            {
                "Error": {
                    "Code": e.response["Error"]["Code"],
                    "Message": f"Failed to download s3://{bucket}/{s3_key} to {local_path}: {e.response['Error']['Message']}",
                }
            },
            "download_file",
        )


def list_objects(
    prefix: str = "",
    bucket: Optional[str] = None,
    max_keys: int = 1000,
) -> list[dict]:
    """List objects in S3 bucket with optional prefix filter.

    Args:
        prefix: S3 key prefix to filter by (e.g., "films/")
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)
        max_keys: Maximum number of objects to return

    Returns:
        List of dicts with object metadata (key, size, last_modified)
    """
    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client()

    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        objects = []
        for obj in response.get("Contents", []):
            objects.append({
                "key": obj["Key"],
                "size_bytes": obj["Size"],
                "size_mb": obj["Size"] / (1024 * 1024),
                "last_modified": obj["LastModified"],
                "etag": obj["ETag"].strip('"'),
            })

        return objects
    except ClientError as e:
        raise ClientError(
            {
                "Error": {
                    "Code": e.response["Error"]["Code"],
                    "Message": f"Failed to list objects in s3://{bucket}/{prefix}: {e.response['Error']['Message']}",
                }
            },
            "list_objects",
        )


def delete_object(
    s3_key: str,
    bucket: Optional[str] = None,
) -> dict:
    """Delete an object from S3.

    Args:
        s3_key: S3 object key to delete
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)

    Returns:
        Dict with deletion confirmation
    """
    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client()

    try:
        s3_client.delete_object(Bucket=bucket, Key=s3_key)

        return {
            "bucket": bucket,
            "key": s3_key,
            "deleted": True,
        }
    except ClientError as e:
        raise ClientError(
            {
                "Error": {
                    "Code": e.response["Error"]["Code"],
                    "Message": f"Failed to delete s3://{bucket}/{s3_key}: {e.response['Error']['Message']}",
                }
            },
            "delete_object",
        )


def object_exists(
    s3_key: str,
    bucket: Optional[str] = None,
) -> bool:
    """Check if an object exists in S3.

    Args:
        s3_key: S3 object key to check
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)

    Returns:
        True if object exists, False otherwise
    """
    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client()

    try:
        s3_client.head_object(Bucket=bucket, Key=s3_key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def get_object_metadata(
    s3_key: str,
    bucket: Optional[str] = None,
) -> dict:
    """Get metadata for an S3 object.

    Args:
        s3_key: S3 object key
        bucket: S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)

    Returns:
        Dict with object metadata

    Raises:
        ClientError: If object doesn't exist or request fails
    """
    if bucket is None:
        bucket = os.getenv("RUNPOD_VOLUME_ID")
        if not bucket:
            raise ValueError("bucket must be provided or RUNPOD_VOLUME_ID must be set")

    s3_client = get_s3_client()

    try:
        response = s3_client.head_object(Bucket=bucket, Key=s3_key)

        return {
            "bucket": bucket,
            "key": s3_key,
            "size_bytes": response["ContentLength"],
            "size_mb": response["ContentLength"] / (1024 * 1024),
            "last_modified": response["LastModified"],
            "etag": response["ETag"].strip('"'),
            "content_type": response.get("ContentType"),
            "metadata": response.get("Metadata", {}),
        }
    except ClientError as e:
        raise ClientError(
            {
                "Error": {
                    "Code": e.response["Error"]["Code"],
                    "Message": f"Failed to get metadata for s3://{bucket}/{s3_key}: {e.response['Error']['Message']}",
                }
            },
            "get_object_metadata",
        )
