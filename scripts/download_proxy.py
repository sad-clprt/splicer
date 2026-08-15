#!/usr/bin/env python3
"""Download the canary proxy file from S3."""

import os
import boto3
from pathlib import Path

# Configure S3 client
s3_client = boto3.client(
    "s3",
    endpoint_url="https://s3api-eu-ro-1.runpod.io",
    region_name="EU-RO-1",
    aws_access_key_id="user_30hSgon3u92BEzzXGYKLcuSxPun",
    aws_secret_access_key="rps_CCV7L1IW2IA54IS71IFYNHK482HZ441U774LZSM61oi7au",
)

bucket = "tn1qxkkw94"
s3_key = "films/945c6475-a629-4140-9968-9135d716565d/1080p_480p_proxy.mp4"
local_path = "downloads/canary_480p_proxy.mp4"

# Create downloads directory
Path(local_path).parent.mkdir(parents=True, exist_ok=True)

# Download
print(f"📥 Downloading {s3_key} from s3://{bucket}")
s3_client.download_file(bucket, s3_key, local_path)

size_mb = Path(local_path).stat().st_size / (1024 * 1024)
print(f"✅ Downloaded: {size_mb:.2f} MB to {local_path}")
