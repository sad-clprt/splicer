#!/usr/bin/env python3
"""Test updated storage module with S3 API key support."""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.tools import storage

# Test 1: List objects (works with both credential types)
print("Test 1: Listing objects")
print("-" * 50)
objects = storage.list_objects(prefix="films/945c6475-a629-4140-9968-9135d716565d/")
proxy_files = [obj for obj in objects if "proxy" in obj["key"]]
print(f"Found {len(proxy_files)} proxy files:")
for obj in proxy_files:
    print(f"  - {obj['key']} ({obj['size_mb']:.2f} MB)")
print()

# Test 2: Download with S3 API key
print("Test 2: Downloading with S3 API key")
print("-" * 50)
test_file = "films/945c6475-a629-4140-9968-9135d716565d/sample_480p_proxy.mp4"
local_path = "downloads/test_storage_module.mp4"

result = storage.download_file(
    s3_key=test_file,
    local_path=local_path,
    use_api_key=True,
)

print(f"✓ Downloaded successfully")
print(f"  Local: {result['local_path']}")
print(f"  Size: {result['size_mb']:.2f} MB")
print()

# Test 3: Get metadata
print("Test 3: Getting object metadata")
print("-" * 50)
metadata = storage.get_object_metadata(test_file)
print(f"Object: {metadata['key']}")
print(f"Size: {metadata['size_mb']:.2f} MB")
print(f"Last modified: {metadata['last_modified']}")
print(f"Content type: {metadata['content_type']}")
print()

print("✓ All tests passed!")
