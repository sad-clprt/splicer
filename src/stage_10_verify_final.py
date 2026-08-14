"""Stage 10: Verify final output exists and meets quality checks.

Final sanity check: confirms final 1080p video exists, is non-zero size,
and basic metadata is valid before marking pipeline complete.
"""

import pathlib
import subprocess
import sys

from loguru import logger
from rich.console import Console

from . import db

console = Console()


def verify_final(film_id: str, final_path: pathlib.Path | str) -> bool:
    """Verify final output meets basic quality checks.

    Args:
        film_id: unique film identifier
        final_path: path to final assembled 1080p video

    Returns:
        True if verification passes, False otherwise
    """
    logger.info(f"[10_verify_final] Verifying {final_path}")

    try:
        path = pathlib.Path(final_path)
        if not path.exists():
            logger.error(f"Final video not found: {final_path}")
            return False

        size = path.stat().st_size
        if size == 0:
            logger.error(f"Final video is empty: {final_path}")
            return False

        # ffprobe basic checks
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration,codec_name",
            "-of", "default=noprint_wrappers=1",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"ffprobe failed: {result.stderr}")
            return False

        output = result.stdout
        logger.debug(f"ffprobe output:\n{output}")

        # Basic validation: should have width, height, duration, codec
        required = ["width=", "height=", "duration=", "codec_name="]
        for req in required:
            if req not in output:
                logger.error(f"Missing {req} in ffprobe output")
                return False

        conn = db.init_db()
        # Mark video as completed
        conn.execute(
            "UPDATE videos SET status='completed', updated_at=datetime('now') WHERE film_id=?",
            (film_id,),
        )
        conn.close()

        console.print(f"[green]✓[/green] Final video verified: {path} ({size:,} bytes)")
        return True

    except Exception as e:
        logger.exception(f"verify_final failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.10_verify_final <film_id> <final_path>")
        sys.exit(1)

    film_id = sys.argv[1]
    final_path = sys.argv[2]

    success = verify_final(film_id, final_path)
    sys.exit(0 if success else 1)
