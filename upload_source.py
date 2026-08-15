#!/usr/bin/env python3
"""Upload source video to S3 and register in database.

Usage:
    python3 upload_source.py <local_file> <film_id>
"""
import sys
import pathlib

# Add src to path
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import db
from s3 import get_s3_client, upload_file_to_s3, s3_key_for_film, VOLUME_ID


def upload_source(local_file: str, film_id: str):
    """Upload source video to S3 and register as asset."""
    local_path = pathlib.Path(local_file)

    if not local_path.exists():
        print(f"Error: File not found: {local_path}")
        return 1

    # Generate S3 key
    s3_key = s3_key_for_film(film_id, "1080p.mp4")

    print(f"Local file: {local_path}")
    print(f"Size: {local_path.stat().st_size / (1024**3):.2f} GB")
    print(f"S3 key: {s3_key}")
    print(f"Bucket: {VOLUME_ID}")
    print()

    # Upload to S3
    print("Uploading to S3...")
    s3 = get_s3_client()

    try:
        result = upload_file_to_s3(s3, VOLUME_ID, local_path, s3_key)
        print(f"✓ Upload complete: {result['size_bytes'] / (1024**3):.2f} GB")
        print(f"  ETag: {result['etag']}")
    except Exception as e:
        print(f"✗ Upload failed: {e}")
        return 1

    # Register in database
    print("\nRegistering asset in database...")
    conn = db.get_conn()

    try:
        # Check if film exists
        film = conn.execute("SELECT id FROM films WHERE id = ?", (film_id,)).fetchone()
        if not film:
            print(f"✗ Film not found in database: {film_id}")
            return 1

        # Check if asset already exists
        existing = conn.execute(
            "SELECT id FROM assets WHERE film_id = ? AND kind = ?",
            (film_id, "source_1080p")
        ).fetchone()

        if existing:
            # Update existing
            conn.execute(
                """UPDATE assets
                   SET s3_key = ?, bucket = ?, size_bytes = ?, status = 'available'
                   WHERE id = ?""",
                (s3_key, VOLUME_ID, result['size_bytes'], existing[0])
            )
            print(f"✓ Updated existing asset: {existing[0]}")
        else:
            # Insert new
            import uuid
            asset_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO assets (id, film_id, kind, s3_key, bucket, size_bytes, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (asset_id, film_id, "source_1080p", s3_key, VOLUME_ID, result['size_bytes'], "available")
            )
            print(f"✓ Created new asset: {asset_id}")

        conn.commit()

    except Exception as e:
        print(f"✗ Database update failed: {e}")
        return 1
    finally:
        conn.close()

    print("\n✓ Upload complete and registered")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        print("\nExample:")
        print("  python3 upload_source.py films/i_am_legend_ed264664/source.mp4 945c6475-a629-4140-9968-9135d716565d")
        sys.exit(1)

    sys.exit(upload_source(sys.argv[1], sys.argv[2]))
