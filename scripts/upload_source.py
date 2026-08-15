#!/usr/bin/env python3
"""Upload source video files to S3 storage for processing."""

import argparse
import sys
from pathlib import Path

# Add parent directory to path to import lib
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.tools.storage import upload_file, object_exists


def main():
    parser = argparse.ArgumentParser(description="Upload source video to S3")
    parser.add_argument("local_path", help="Path to local video file")
    parser.add_argument("s3_key", help="S3 key (path) to upload to")
    parser.add_argument("--bucket", help="S3 bucket name (defaults to RUNPOD_VOLUME_ID env var)")
    parser.add_argument("--force", action="store_true", help="Overwrite if file already exists")

    args = parser.parse_args()

    # Check if local file exists
    local_file = Path(args.local_path)
    if not local_file.exists():
        print(f"❌ Error: Local file not found: {args.local_path}")
        sys.exit(1)

    # Check if S3 object already exists
    if not args.force and object_exists(args.s3_key, args.bucket):
        print(f"❌ Error: S3 object already exists: {args.s3_key}")
        print("   Use --force to overwrite")
        sys.exit(1)

    # Upload file
    print(f"📤 Uploading {args.local_path} to s3://{args.bucket or 'default'}/{args.s3_key}")

    try:
        result = upload_file(
            local_path=args.local_path,
            s3_key=args.s3_key,
            bucket=args.bucket,
        )

        print(f"✅ Upload complete!")
        print(f"   Size: {result['size_mb']:.2f} MB")
        print(f"   URI: {result['s3_uri']}")

    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
