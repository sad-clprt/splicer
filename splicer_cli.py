"""
Splicer CLI - Command-line interface for film processing tools.

Usage:
    splicer film create "Title" --source path/to/video.mp4
    splicer film list
    splicer film info <film_id>
    splicer proxy generate <film_id>
    splicer audio analyze <film_id>
    splicer script generate <film_id>
    splicer tts generate <film_id>
    splicer assemble <film_id>
    splicer safety check <film_id>
"""

import sys
from pathlib import Path
import json
import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib import db, film_manager
from lib.tools import proxy, audio, knowledge, visual, script, tts, assemble, safety


console = Console()


@click.group()
def cli():
    """Splicer - Tool-based film processing for YouTube recaps."""
    pass


# ============================================================================
# FILM MANAGEMENT COMMANDS
# ============================================================================

@cli.group()
def film():
    """Film management commands."""
    pass


@film.command("create")
@click.argument("title")
@click.option("--source", type=click.Path(exists=True), help="Path to source video file")
@click.option("--year", type=int, help="Release year")
@click.option("--director", help="Director name")
@click.option("--genre", help="Genre/category")
@click.option("--tags", help="Comma-separated tags")
@click.option("--notes", help="Notes about the film")
@click.option("--film-id", help="Custom film ID (auto-generated if not provided)")
def film_create(title, source, year, director, genre, tags, notes, film_id):
    """Create a new film entry."""
    try:
        tags_list = [t.strip() for t in tags.split(",")] if tags else None
        source_path = Path(source) if source else None

        film_id = film_manager.create_film(
            title=title,
            source_path=source_path,
            year=year,
            director=director,
            genre=genre,
            tags=tags_list,
            notes=notes,
            film_id=film_id,
        )

        console.print(f"[green]✓[/green] Created film: {film_id}")
        console.print(f"  Location: films/{film_id}/")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@film.command("list")
@click.option("--status", help="Filter by status (new, in_progress, completed, failed)")
@click.option("--year", type=int, help="Filter by year")
@click.option("--title", help="Search by title")
@click.option("--limit", type=int, default=20, help="Max results")
def film_list(status, year, title, limit):
    """List films with optional filters."""
    try:
        films = film_manager.list_films(
            status=status,
            year=year,
            title=title,
            limit=limit
        )

        if not films:
            console.print("[yellow]No films found[/yellow]")
            return

        table = Table(title=f"Films ({len(films)})")
        table.add_column("Film ID", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Year")
        table.add_column("Status", style="yellow")
        table.add_column("Stage")

        for f in films:
            table.add_row(
                f["film_id"],
                f["title"],
                str(f["year"]) if f["year"] else "-",
                f["status"] or "new",
                f["current_stage"] or "-"
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@film.command("info")
@click.argument("film_id")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def film_info(film_id, json_output):
    """Show detailed film information."""
    try:
        info = film_manager.get_film_info(film_id)

        if json_output:
            click.echo(json.dumps(info, indent=2, default=str))
            return

        console.print(f"\n[bold cyan]{info['title']}[/bold cyan]")
        if info.get("year"):
            console.print(f"Year: {info['year']}")
        if info.get("director"):
            console.print(f"Director: {info['director']}")
        if info.get("genre"):
            console.print(f"Genre: {info['genre']}")

        console.print(f"\n[bold]Status:[/bold] {info['status']}")
        console.print(f"[bold]Current Stage:[/bold] {info.get('current_stage', 'none')}")

        if info.get("manifest"):
            console.print("\n[bold]Pipeline Status:[/bold]")
            for stage, status_data in info["manifest"]["status"].items():
                status = status_data.get("status", "unknown")
                emoji = "✓" if status == "completed" else "○" if status == "not_started" else "●"
                console.print(f"  {emoji} {stage}: {status}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@film.command("delete")
@click.argument("film_id")
@click.option("--remove-files", is_flag=True, help="Also delete film directory")
@click.confirmation_option(prompt="Are you sure you want to delete this film?")
def film_delete(film_id, remove_files):
    """Delete a film from the index."""
    try:
        film_manager.delete_film(film_id, remove_files=remove_files)
        console.print(f"[green]✓[/green] Deleted film: {film_id}")
        if remove_files:
            console.print("  Files removed")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# PROXY COMMANDS
# ============================================================================

@cli.group()
def proxy_cmd():
    """Proxy generation commands."""
    pass


@proxy_cmd.command("generate")
@click.argument("film_id")
@click.option("--transcoder", type=click.Choice(["auto", "pynvc", "ffmpeg"]), default="auto", help="Transcoder engine: auto (pynvc fallback ffmpeg), pynvc (NVIDIA Video SDK), ffmpeg")
@click.option("--overwrite", is_flag=True, help="Overwrite existing proxy")
def proxy_generate(film_id, transcoder, overwrite):
    """Generate 480p proxy video."""
    try:
        console.print(f"Generating proxy for {film_id} via {transcoder}...")
        job_id = proxy.generate_proxy(film_id, overwrite=overwrite, transcoder=transcoder)
        console.print(f"[green]✓[/green] Job submitted: {job_id} (transcoder={transcoder})")
        console.print("  Poll with: splicer proxy poll <film_id> <job_id>")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@proxy_cmd.command("poll")
@click.argument("film_id")
@click.argument("job_id")
def proxy_poll(film_id, job_id):
    """Poll proxy generation job status."""
    try:
        status = proxy.poll_proxy(film_id, job_id)
        console.print(f"Status: {status}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@proxy_cmd.command("download")
@click.argument("film_id")
@click.argument("output_url")
def proxy_download(film_id, output_url):
    """Download proxy video from S3."""
    try:
        console.print(f"Downloading proxy for {film_id}...")
        path = proxy.download_proxy(film_id, output_url)
        console.print(f"[green]✓[/green] Downloaded to: {path}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@proxy_cmd.command("wait")
@click.argument("film_id")
@click.option("--poll-interval", default=10, help="Seconds between status polls")
@click.option("--timeout", default=600, help="Maximum wait time in seconds")
@click.option("--transcoder", type=click.Choice(["auto", "pynvc", "ffmpeg"]), default="auto", help="Transcoder engine")
@click.option("--overwrite", is_flag=True, help="Overwrite existing proxy")
def proxy_wait(film_id, poll_interval, timeout, transcoder, overwrite):
    """Generate proxy and wait for completion."""
    try:
        console.print(f"[cyan]Starting proxy generation for {film_id} via {transcoder}...[/cyan]")
        path = proxy.generate_and_wait(film_id, poll_interval=poll_interval, timeout=timeout, overwrite=overwrite, transcoder=transcoder)
        console.print(f"[green]✓[/green] Proxy generated: {path} (transcoder={transcoder})")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# AUDIO COMMANDS
# ============================================================================

@cli.group()
def audio_cmd():
    """Audio analysis commands."""
    pass


@audio_cmd.command("analyze")
@click.argument("film_id")
@click.option("--source", default="proxy", help="Video source (proxy or source)")
def audio_analyze(film_id, source):
    """Analyze audio with WhisperX."""
    try:
        console.print(f"Analyzing audio for {film_id}...")
        job_id = audio.analyze_audio(film_id, source=source)
        console.print(f"[green]✓[/green] Job submitted: {job_id}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@audio_cmd.command("enrich")
@click.argument("film_id")
def audio_enrich(film_id):
    """Enrich audio analysis with metadata."""
    try:
        console.print(f"Enriching audio for {film_id}...")
        result = audio.enrich_audio(film_id)
        console.print(f"[green]✓[/green] Audio enriched")
        console.print(f"  {result}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# KNOWLEDGE COMMANDS
# ============================================================================

@cli.group()
def knowledge_cmd():
    """Knowledge enrichment commands."""
    pass


@knowledge_cmd.command("enrich")
@click.argument("film_id")
@click.option("--sources", default="tmdb", help="Comma-separated sources (tmdb,omdb)")
def knowledge_enrich(film_id, sources):
    """Enrich film with external knowledge."""
    try:
        sources_list = [s.strip() for s in sources.split(",")]
        console.print(f"Enriching knowledge for {film_id}...")
        result = knowledge.enrich_knowledge(film_id, sources=sources_list)
        console.print(f"[green]✓[/green] Knowledge enriched")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# SCRIPT COMMANDS
# ============================================================================

@cli.group()
def script_cmd():
    """Script generation commands."""
    pass


@script_cmd.command("generate")
@click.argument("film_id")
@click.option("--style", default="engaging", help="Script style")
@click.option("--context", help="Additional context for generation")
def script_generate(film_id, style, context):
    """Generate voiceover script."""
    try:
        console.print(f"Generating script for {film_id}...")
        path = script.generate_script(film_id, style=style, context=context)
        console.print(f"[green]✓[/green] Script generated: {path}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


@script_cmd.command("regenerate")
@click.argument("film_id")
@click.option("--feedback", required=True, help="Feedback on previous version")
@click.option("--style", help="New style")
def script_regenerate(film_id, feedback, style):
    """Regenerate script with feedback."""
    try:
        console.print(f"Regenerating script for {film_id}...")
        path = script.regenerate_script(film_id, feedback=feedback, style=style)
        console.print(f"[green]✓[/green] Script regenerated: {path}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# TTS COMMANDS
# ============================================================================

@cli.group()
def tts_cmd():
    """Text-to-speech commands."""
    pass


@tts_cmd.command("generate")
@click.argument("film_id")
@click.option("--voice", default="default", help="Voice ID")
@click.option("--speed", type=float, default=1.0, help="Playback speed")
def tts_generate(film_id, voice, speed):
    """Generate voiceover from script."""
    try:
        console.print(f"Generating voiceover for {film_id}...")
        job_id = tts.generate_voiceover(film_id, voice=voice, speed=speed)
        console.print(f"[green]✓[/green] Job submitted: {job_id}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# ASSEMBLE COMMANDS
# ============================================================================

@cli.group()
def assemble_cmd():
    """Video assembly commands."""
    pass


@assemble_cmd.command("video")
@click.argument("film_id")
@click.option("--source", default="proxy", help="Base video (proxy or source)")
def assemble_video_cmd(film_id, source):
    """Assemble final video."""
    try:
        console.print(f"Assembling video for {film_id}...")
        path = assemble.assemble_video(film_id, config={"source": source})
        console.print(f"[green]✓[/green] Video assembled: {path}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# ============================================================================
# SAFETY COMMANDS
# ============================================================================

@cli.group()
def safety_cmd():
    """Safety and compliance commands."""
    pass


@safety_cmd.command("check")
@click.argument("film_id")
def safety_check(film_id):
    """Run safety check on final video."""
    try:
        console.print(f"Running safety check for {film_id}...")
        report = safety.run_safety_check(film_id)

        if report["passed"]:
            console.print(f"[green]✓[/green] Safety check passed")
        else:
            console.print(f"[red]✗[/red] Safety check failed")
            console.print(f"  Issues: {len(report['issues'])}")
            for issue in report["issues"]:
                console.print(f"    - {issue}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


# Register command groups with 'splicer' prefix names
cli.add_command(proxy_cmd, name="proxy")
cli.add_command(audio_cmd, name="audio")
cli.add_command(knowledge_cmd, name="knowledge")
cli.add_command(script_cmd, name="script")
cli.add_command(tts_cmd, name="tts")
cli.add_command(assemble_cmd, name="assemble")
cli.add_command(safety_cmd, name="safety")


if __name__ == "__main__":
    cli()
