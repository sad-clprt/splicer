#!/usr/bin/env python3
"""Generate a presigned URL for downloading the proxy file."""

import boto3
from botocore.client import Config

# Configure S3 client
s3_client = boto3.client(
    "s3",
    endpoint_url="https://s3api-eu-ro-1.runpod.io",
    region_name="EU-RO-1",
    aws_access_key_id="user_30hSgon3u92BEzzXGYKLcuSxPun",
    aws_secret_access_key="rps_CCV7L1IW2IA54IS71IFYNHK482HZ441U774LZSM61oi7au",
    config=Config(signature_version='s3v4')
)

bucket = "tn1qxkkw94"
s3_key = "films/945c6475-a629-4140-9968-9135d716565d/1080p_480p_proxy.mp4"

try:
    # Generate presigned URL valid for 1 hour
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': s3_key},
        ExpiresIn=3600
    )

    print(f"✅ Presigned URL generated:")
    print(url)
    print(f"\nDownload with:")
    print(f"curl -o downloads/canary_480p_proxy.mp4 '{url}'")

except Exception as e:
    print(f"❌ Error: {e}")
