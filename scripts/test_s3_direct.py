#!/usr/bin/env python3
"""Test S3 access with new API key credentials."""

import os
from dotenv import load_dotenv
import boto3

load_dotenv()

# Use the new S3 API key credentials
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("S3_ACESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    endpoint_url=os.getenv("AWS_S3_ENDPOINT"),
    region_name=os.getenv("AWS_S3_REGION"),
)

bucket = os.getenv("RUNPOD_VOLUME_ID")
print(f"Testing S3 access to bucket: {bucket}")
print(f"Using access key: {os.getenv('S3_ACESS_KEY')}")
print(f"Endpoint: {os.getenv('AWS_S3_ENDPOINT')}")
print()

try:
    # Test listing
    response = s3_client.list_objects_v2(
        Bucket=bucket,
        Prefix="films/945c6475-a629-4140-9968-9135d716565d/",
    )

    if "Contents" in response:
        print(f"Found {len(response['Contents'])} objects:")
        for obj in response["Contents"]:
            if "proxy" in obj["Key"]:
                print(f"  - {obj['Key']} ({obj['Size'] / 1024 / 1024:.2f} MB)")
    else:
        print("No objects found")

except Exception as e:
    print(f"Error: {e}")
