"""Generic job polling utility for any RunPod job.

Use this to poll and download results from audio/VLM/TTS/safety jobs.
"""

import pathlib
import sys

from loguru import logger
from rich.console import Console

from . import db
from . import runpod_client
from . import s3

console = Console()


def poll_job(
    film_id: str,
    job_id: str,
    endpoint_name: str,
    kind: str,
    output_dir: pathlib.Path | str = "./output",
) -> dict | None:
    """Poll RunPod job until complete and process result.

    Args:
        film_id: unique film identifier
        job_id: RunPod job ID to poll
        endpoint_name: endpoint name ('audio', 'vlm', 'tts', 'safety')
        kind: job kind for DB tracking
        output_dir: local directory to save outputs

    Returns:
        Job output dict if successful, None otherwise
    """
    logger.info(f"[poll_job] Polling {endpoint_name} job {job_id}")

    try:
        endpoint_ids = runpod_client.get_endpoint_ids()
        endpoint_id = endpoint_ids.get(endpoint_name)
        if not endpoint_id:
            logger.error(f"RUNPOD_ENDPOINT_{endpoint_name.upper()} not set in .env")
            return None

        client = runpod_client.RunPodClient(endpoint_id)

        console.print(f"Polling {endpoint_name} job {job_id}...", style="dim")
        result = client.poll_until_complete(job_id, poll_interval=15, max_wait=3600)

        output = result.get("output", {})
        logger.info(f"Job {job_id} completed with output keys: {list(output.keys())}")

        # Update DB
        conn = db.init_db()
        db.update_job(conn, job_id=job_id, status="completed")

        # Handle different output types
        if kind == "audio":
            # Audio enrichment outputs audio_enrich_key
            audio_key = output.get("audio_enrich_key")
            if audio_key:
                db.upsert_asset(
                    conn,
                    film_id=film_id,
                    kind="audio_enrich",
                    s3_key=audio_key,
                    bucket=s3.VOLUME_ID,
                    status="available",
                )
                console.print(f"[green]✓[/green] Audio enrichment ready: {audio_key}")

        elif kind == "vlm":
            # VLM outputs stage1/stage2/stage3 keys
            stage3_key = output.get("stage3_key")
            if stage3_key:
                db.upsert_asset(
                    conn,
                    film_id=film_id,
                    kind="vlm",
                    s3_key=stage3_key,
                    bucket=s3.VOLUME_ID,
                    status="available",
                )
                console.print(f"[green]✓[/green] VLM stage3 ready: {stage3_key}")

        elif kind == "tts":
            # TTS outputs audio_base64
            audio_b64 = output.get("audio_base64")
            if audio_b64:
                import base64

                audio_bytes = base64.b64decode(audio_b64)
                dest = pathlib.Path(output_dir) / f"{film_id}_tts.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(audio_bytes)
                console.print(f"[green]✓[/green] TTS audio downloaded: {dest} ({len(audio_bytes):,} bytes)")

        elif kind == "safety":
            # Safety outputs violations list
            violations = output.get("violations", [])
            console.print(f"[green]✓[/green] Safety check complete: {len(violations)} violations")
            if violations:
                logger.warning(f"Safety violations found: {violations}")

        conn.close()
        return output

    except Exception as e:
        logger.exception(f"poll_job failed: {e}")
        conn = db.init_db()
        db.update_job(conn, job_id=job_id, status="failed", error=str(e))
        conn.close()
        return None


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python -m src.poll_job <film_id> <job_id> <endpoint_name> <kind> [output_dir]")
        print("endpoint_name: audio | vlm | tts | safety")
        print("kind: audio | vlm | tts | safety")
        sys.exit(1)

    film_id = sys.argv[1]
    job_id = sys.argv[2]
    endpoint_name = sys.argv[3]
    kind = sys.argv[4]
    output_dir = sys.argv[5] if len(sys.argv) > 5 else "./output"

    result = poll_job(film_id, job_id, endpoint_name, kind, output_dir)
    sys.exit(0 if result else 1)
