"""RunPod S3 (Network Volume) helpers.

Volume: tn1qxkkw94 (splicer-films) on EU-RO-1, endpoint https://s3api-eu-ro-1.runpod.io
Bucket == volume ID, Key == object path e.g. films/<film_id>/1080p.mp4
"""

import os
import pathlib

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

S3_ENDPOINT = os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io")
S3_REGION = os.getenv("AWS_S3_REGION", "EU-RO-1")
VOLUME_ID = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=S3_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 10, "mode": "standard"}),
    )


def s3_key_for_film(film_id: str, filename: str) -> str:
    """Generate S3 key for a film asset."""
    safe = filename.replace(" ", "_")
    return f"films/{film_id}/{safe}"


def head_object_safe(s3, bucket: str, key: str):
    """Try head_object, return None on error instead of raising."""
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None


def download_s3_with_fallback(s3, bucket: str, key: str, dest: str | pathlib.Path) -> None:
    """Download S3 key to dest, handling RunPod HeadObject 403 via list + streaming get_object.

    RunPod S3 can return 403 Forbidden on HeadObject (used internally by
    ``download_file``) even when the caller has GetObject permission. In that
    case we verify existence via ``list_objects_v2`` and stream the object via
    ``get_object`` which bypasses the HeadObject check.

    Args:
        s3: boto3 S3 client (from ``get_s3_client``).
        bucket: volume/bucket ID (e.g. ``tn1qxkkw94``).
        key: object key (e.g. ``films/<id>/1080p.mp4``).
        dest: local file path (str or Path); parent dirs are created.

    Raises:
        FileNotFoundError: key does not exist
        RuntimeError: download failed for other reasons
    """
    dest_path = pathlib.Path(dest)
    try:
        s3.download_file(bucket, key, str(dest_path))
        return
    except Exception as e:
        err = str(e)
        if "404" in err or "NoSuchKey" in err or "Not Found" in err:
            raise FileNotFoundError(f"S3 key not found: {key}") from e
        if "403" in err or "Forbidden" in err:
            try:
                lst = s3.list_objects_v2(Bucket=bucket, Prefix=key)
                found = any(o["Key"] == key for o in lst.get("Contents", []))
                if not found:
                    raise FileNotFoundError(f"S3 key not found via list: {key}") from e
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = resp["Body"]
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = body.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                return
            except Exception as e2:
                if isinstance(e2, FileNotFoundError):
                    raise
                raise RuntimeError(f"S3 download fallback failed for {key}: {e2}") from e2
        raise
