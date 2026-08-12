"""RunPod S3 (Network Volume) helpers for parallel uploads.

Volume: tn1qxkkw94 (splicer-films) on EU-RO-1, endpoint https://s3api-eu-ro-1.runpod.io
Bucket == volume ID, Key == object path e.g. films/<film_id>/1080p.mp4
"""

import os

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
    # Keep original filename sanitized, ensure unique per film
    safe = filename.replace(" ", "_")
    return f"films/{film_id}/{safe}"


def create_multipart_upload(s3, bucket: str, key: str) -> str:
    resp = s3.create_multipart_upload(Bucket=bucket, Key=key)
    return resp["UploadId"]


def presigned_part_urls(
    s3, bucket: str, key: str, upload_id: str, part_count: int, expires: int = 3600
) -> list[str]:
    urls: list[str] = []
    for part_number in range(1, part_count + 1):
        url = s3.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
            ExpiresIn=expires,
        )
        urls.append(url)
    return urls


def complete_multipart_upload(s3, bucket: str, key: str, upload_id: str, parts: list[dict]) -> dict:
    # parts: [{"ETag": "...", "PartNumber": 1}, ...] sorted
    parts_sorted = sorted(parts, key=lambda p: p["PartNumber"])
    return s3.complete_multipart_upload(
        Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts_sorted}
    )


def head_object_safe(s3, bucket: str, key: str):
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None
