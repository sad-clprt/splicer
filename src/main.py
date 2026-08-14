"""Main orchestrator for splicer pipeline.

Runs all stages sequentially: proxy → audio → VLM → script → TTS → assemble → safety → verify.
Uses SQLite for state and RunPod Serverless for GPU work.

Usage:
    python -m src.main <film_id> <source_s3_key>

Example:
    python -m src.main 945c6475-a629-4140-9968-9135d716565d films/945c6475-a629-4140-9968-9135d716565d/I.Am.Legend.1080p.mp4
"""

import sys
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn

# Import stage functions
from . import db
from .stage_00_check_source import check_source
from .stage_01_proxy_generate import proxy_generate

console = Console()


def run_pipeline(film_id: str, source_s3_key: str, output_dir: str = "./output") -> bool:
    """Run full splicer pipeline end-to-end.

    Args:
        film_id: unique film identifier
        source_s3_key: S3 key for source 1080p film
        output_dir: local directory for intermediate and final outputs

    Returns:
        True if pipeline completes successfully, False otherwise
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            f"[bold cyan]Splicer Pipeline[/bold cyan]\n"
            f"Film ID: {film_id}\n"
            f"Source: {source_s3_key}\n"
            f"Output: {output_dir}",
            border_style="cyan",
        )
    )

    # Initialize database
    conn = db.init_db()
    db.ensure_film(conn, film_id)
    conn.close()

    stages = [
        ("00_check_source", lambda: check_source(film_id, source_s3_key)),
        ("01_proxy_generate", lambda: proxy_generate(film_id, source_s3_key)),
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for stage_name, stage_fn in stages:
            task = progress.add_task(f"[cyan]{stage_name}...", total=None)
            try:
                result = stage_fn()
                if not result:
                    progress.update(task, description=f"[red]✗ {stage_name} failed")
                    logger.error(f"Stage {stage_name} failed")
                    return False
                progress.update(task, description=f"[green]✓ {stage_name}")
            except Exception as e:
                progress.update(task, description=f"[red]✗ {stage_name} error")
                logger.exception(f"Stage {stage_name} raised exception: {e}")
                return False

    # Stage 02: proxy_download needs job_id from stage 01
    # For now, we'll need to track this in DB or return from stage 01
    console.print("[yellow]Pipeline paused: manual proxy_download step required[/yellow]")
    console.print("Run: python -m src.02_proxy_download <film_id> <job_id>")

    # TODO: Continue with audio, VLM, script, TTS, assemble, safety, verify stages
    # These will be added incrementally

    console.print(Panel.fit("[bold green]Pipeline stages 00-01 complete![/bold green]", border_style="green"))
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        console.print("[red]Usage:[/red] python -m src.main <film_id> <source_s3_key> [output_dir]")
        console.print("\n[yellow]Example:[/yellow]")
        console.print(
            "  python -m src.main 945c6475-a629-4140-9968-9135d716565d "
            "films/945c6475-a629-4140-9968-9135d716565d/I.Am.Legend.1080p.mp4"
        )
        sys.exit(1)

    film_id = sys.argv[1]
    source_s3_key = sys.argv[2]
    output_dir = sys.argv[3] if len(sys.argv) > 3 else "./output"

    success = run_pipeline(film_id, source_s3_key, output_dir)
    sys.exit(0 if success else 1)
