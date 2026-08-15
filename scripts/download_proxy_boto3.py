#!/usr/bin/env python3
"""Download proxy video file from Runpod S3 using boto3."""

import os
from pathlib import Path
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

load_dotenv()

# Configuration
bucket = os.getenv("RUNPOD_VOLUME_ID")
s3_key = "films/945c6475-a629-4140-9968-9135d716565d/sample_480p_proxy.mp4"
local_file = Path("downloads/sample_480p_proxy.mp4")

# Create S3 client with new API key credentials
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("S3_ACESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    endpoint_url=os.getenv("AWS_S3_ENDPOINT"),
    region_name=os.getenv("AWS_S3_REGION"),
)

print(f"Downloading from S3:")
print(f"  Bucket: {bucket}")
print(f"  Key: {s3_key}")
print(f"  Local: {local_file}")
print()

# Create downloads directory
local_file.parent.mkdir(parents=True, exist_ok=True)

try:
    # Get file info
    response = s3_client.head_object(Bucket=bucket, Key=s3_key)
    file_size = response["ContentLength"]
    print(f"File size: {file_size / 1024 / 1024:.2f} MB")
    print("Downloading...")

    # Download using get_object and write manually
    response = s3_client.get_object(Bucket=bucket, Key=s3_key)
    body = response["Body"]

    bytes_downloaded = 0
    chunk_size = 8192  # 8KB chunks

    with open(local_file, "wb") as f:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            bytes_downloaded += len(chunk)

            # Show progress every MB
            if bytes_downloaded % (1024 * 1024) < chunk_size:
                percent = (bytes_downloaded / file_size) * 100
                print(f"\rProgress: {percent:.1f}% ({bytes_downloaded / 1024 / 1024:.1f} MB)", end="", flush=True)

    print(f"\n\nDownload complete: {local_file}")
    print(f"Downloaded: {local_file.stat().st_size / 1024 / 1024:.2f} MB")

except ClientError as e:
    print(f"Error downloading file: {e}")
    exit(1)
except Exception as e:
    print(f"Unexpected error: {e}")
    exit(1)
