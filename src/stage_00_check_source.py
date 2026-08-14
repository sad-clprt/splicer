"""Stage 00: Check source film exists on S3 and register in DB.

Verifies the source 1080p film exists on RunPod S3, records metadata.
"""

import sys

from loguru import logger
from rich.console import Console

from . import db
from . import s3

console = Console()


def check_source(film_id: str, source_key: str) -> bool:
    """Verify source film exists on S3 and register in DB.

    Args:
        film_id: unique film identifier
        source_key: S3 key for source 1080p file, e.g. films/<id>/I.Am.Legend.1080p.mp4

    Returns:
        True if source exists and registered, False otherwise
    """
    logger.info(f"[00_check_source] Checking {source_key}")

    try:
        s3_client = s3.get_s3_client()
        head = s3.head_object_safe(s3_client, s3.VOLUME_ID, source_key)

        if head is None:
            logger.error(f"Source film not found: {source_key}")
            return False

        size_bytes = head.get("ContentLength", 0)
        logger.info(f"Source found: {source_key} ({size_bytes:,} bytes)")

        conn = db.init_db()
        db.ensure_film(conn, film_id, title="I Am Legend", year=2007)
        db.upsert_asset(
            conn,
            film_id=film_id,
            kind="source_1080p",
            s3_key=source_key,
            bucket=s3.VOLUME_ID,
            s3_endpoint=s3.S3_ENDPOINT,
            datacenter=s3.S3_REGION,
            size_bytes=size_bytes,
            status="available",
        )
        conn.close()

        console.print(f"[green]✓[/green] Source registered: {source_key}")
        return True

    except Exception as e:
        logger.exception(f"check_source failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.00_check_source <film_id> <s3_key>")
        sys.exit(1)

    film_id = sys.argv[1]
    source_key = sys.argv[2]

    success = check_source(film_id, source_key)
    sys.exit(0 if success else 1)
