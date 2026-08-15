#!/usr/bin/env python3
"""Test S3 credentials by listing objects."""

import boto3

# Configure S3 client
s3_client = boto3.client(
    "s3",
    endpoint_url="https://s3api-eu-ro-1.runpod.io",
    region_name="EU-RO-1",
    aws_access_key_id="user_30hSgon3u92BEzzXGYKLcuSxPun",
    aws_secret_access_key="rps_CCV7L1IW2IA54IS71IFYNHK482HZ441U774LZSM61oi7au",
)

bucket = "tn1qxkkw94"

try:
    # Try to list objects in the films directory
    response = s3_client.list_objects_v2(
        Bucket=bucket,
        Prefix="films/945c6475-a629-4140-9968-9135d716565d/",
        MaxKeys=10
    )

    print(f"✅ Connected to s3://{bucket}")
    print(f"\nFiles in films/945c6475-a629-4140-9968-9135d716565d/:")
    for obj in response.get('Contents', []):
        size_mb = obj['Size'] / (1024 * 1024)
        print(f"  - {obj['Key']} ({size_mb:.2f} MB)")

except Exception as e:
    print(f"❌ Error: {e}")
