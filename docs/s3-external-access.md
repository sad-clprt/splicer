# S3 External Access Setup

## Overview

Runpod network volumes support S3-compatible API access with two distinct credential modes:

1. **Internal (Endpoint Environment Variables)** - Restricted to Runpod infrastructure
2. **External (S3 API Keys)** - Works from any location including local machines

## Credential Types

### Internal Credentials (Serverless Workers/Pods)

Used automatically within Runpod serverless workers and pods:

```bash
AWS_ACCESS_KEY_ID=user_30hSgon3u92BEzzXGYKLcuSxPun
AWS_SECRET_ACCESS_KEY=rps_***  # Different secret than S3 API key
AWS_S3_ENDPOINT=https://s3api-eu-ro-1.runpod.io
AWS_S3_REGION=EU-RO-1
RUNPOD_VOLUME_ID=tn1qxkkw94
```

These credentials are provided in the serverless endpoint environment and work **only from within Runpod infrastructure**.

### External Credentials (S3 API Keys)

Created in Runpod console for external access:

```bash
S3_ACESS_KEY=user_30hSgon3u92BEzzXGYKLcuSxPun  # Same user ID
S3_SECRET_ACCESS_KEY=rps_HH8YOUEFV11FA6XH0OH34RB6M2H16HSWYZMV9VY30ahpdj  # Different secret
```

These credentials work from **any location** including local machines, CI/CD, and external services.

## Creating S3 API Keys

1. Go to https://www.console.runpod.io/user/settings
2. Expand "S3 API Keys" section
3. Click "Create an S3 API key"
4. Name it (e.g., "local-access")
5. Save both:
   - Access key (starts with `user_`)
   - Secret (starts with `rps_`)

**Important:** The secret is shown only once - save it immediately.

## Usage in Code

### Using lib/tools/storage Module

The storage module automatically handles both credential types:

```python
from lib.tools import storage

# List objects (works with both credential types)
objects = storage.list_objects(prefix="films/")

# Upload (internal credentials - from workers)
storage.upload_file("local.mp4", "films/xyz/video.mp4")

# Download (external credentials - from local machine)
storage.download_file(
    "films/xyz/video.mp4",
    "local.mp4",
    use_api_key=True  # Use S3 API key for external access
)
```

### Automatic Fallback

The `get_s3_client()` function automatically falls back:
- If `use_api_key=True` but S3 API key not available → falls back to internal credentials
- If `use_api_key=False` but internal credentials not available → falls back to S3 API key

This means code works in both environments without modification.

## Boto3 Compatibility Notes

When using S3 API keys, some boto3 operations have limitations:

- ✓ `list_objects_v2()` - Works perfectly
- ✓ `get_object()` - Works perfectly  
- ✓ `head_object()` - Works perfectly
- ✗ `download_file()` - Fails with 403 (uses additional internal operations)

**Solution:** Our storage module uses `get_object()` and writes files manually, which works reliably with S3 API keys.

## Rclone Issues

Rclone configuration did not work with Runpod S3 API keys despite boto3 working correctly. The signature authentication consistently failed. Use boto3-based tools instead.

## Testing

Test S3 access with:

```bash
# Test storage module
uv run python scripts/test_storage_module.py

# Test permissions
uv run python scripts/test_s3_permissions.py

# Download proxy file
uv run python scripts/download_proxy_boto3.py
```

## Environment Variables

Complete `.env` configuration:

```bash
# Runpod S3 (Internal - for serverless workers)
AWS_ACCESS_KEY_ID="user_30hSgon3u92BEzzXGYKLcuSxPun"
AWS_SECRET_ACCESS_KEY="rps_CCV7L1IW2IA54IS71IFYNHK482HZ441U774LZSM61oi7au"
AWS_S3_ENDPOINT="https://s3api-eu-ro-1.runpod.io"
AWS_S3_REGION="EU-RO-1"
RUNPOD_VOLUME_ID="tn1qxkkw94"

# S3 API Keys (External - for local machine)
S3_ACESS_KEY="user_30hSgon3u92BEzzXGYKLcuSxPun"
S3_SECRET_ACCESS_KEY="rps_HH8YOUEFV11FA6XH0OH34RB6M2H16HSWYZMV9VY30ahpdj"
```

## References

- [Runpod S3 API Documentation](https://docs.runpod.io/storage/s3-api)
- [AWS CLI Configuration](https://docs.runpod.io/storage/s3-api#configure-aws-cli)
- [Network Volumes](https://docs.runpod.io/storage/network-volumes)
