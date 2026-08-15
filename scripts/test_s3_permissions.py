#!/usr/bin/env python3
"""Test S3 API key permissions."""

import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

load_dotenv()

bucket = os.getenv("RUNPOD_VOLUME_ID")
s3_key = "films/945c6475-a629-4140-9968-9135d716565d/sample_480p_proxy.mp4"

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("S3_ACESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    endpoint_url=os.getenv("AWS_S3_ENDPOINT"),
    region_name=os.getenv("AWS_S3_REGION"),
)

print(f"Testing permissions for: {s3_key}")
print()

# Test 1: list_objects_v2 (we know this works)
print("✓ list_objects_v2: SUCCESS (already confirmed)")

# Test 2: head_object
print("Testing head_object...", end=" ", flush=True)
try:
    s3_client.head_object(Bucket=bucket, Key=s3_key)
    print("✓ SUCCESS")
except ClientError as e:
    print(f"✗ FAILED: {e}")

# Test 3: get_object
print("Testing get_object...", end=" ", flush=True)
try:
    response = s3_client.get_object(Bucket=bucket, Key=s3_key)
    # Read just first 1KB to test access
    data = response["Body"].read(1024)
    print(f"✓ SUCCESS (read {len(data)} bytes)")
except ClientError as e:
    print(f"✗ FAILED: {e}")
