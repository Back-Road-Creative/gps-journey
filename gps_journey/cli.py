"""Command-line interface using Typer."""

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler

from gps_journey.core.gpx_parser import GPXParser

app = typer.Typer(
    name="gps-journey",
    help="GPS Journey Service - Transform GPS tracks into travel narratives",
    add_completion=False,
)

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


@app.command()
def process(
    gpx_file: Path = typer.Argument(..., help="Path to GPX file", exists=True),  # noqa: B008
    output: Path | None = typer.Option(None, "--output", "-o", help="Output markdown file"),  # noqa: B008
    geocode: bool = typer.Option(False, "--geocode", "-g", help="Enable geocoding"),
    photos: bool = typer.Option(False, "--photos", "-p", help="Include Google Photos"),
    album: str | None = typer.Option(None, "--album", "-a", help="Google Photos album name"),
    map_output: bool = typer.Option(False, "--map", "-m", help="Generate interactive map"),
    static_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--static-dir",
        help=(
            "Hugo static directory for photo mappings (default: none). Handed to the "
            "generator, which only reads photo mappings when given a gallery path; "
            "`process` does not pass one yet, so this has no effect here"
        ),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Process a GPX file and generate journey content."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    try:
        console.print(f"[bold blue]Processing GPX file:[/bold blue] {gpx_file}")

        # Parse GPX
        parser = GPXParser()
        journey = parser.parse(gpx_file)

        console.print(
            f"[green]✓[/green] Parsed {len(journey.waypoints)} waypoints\n"
            f"  Duration: {journey.duration_days} days, {journey.duration_hours:.1f} hours"
        )

        if journey.statistics:
            stats = journey.statistics
            console.print(
                f"  Distance: {stats.total_distance_km:.1f} km "
                f"({stats.total_distance_miles:.1f} miles)\n"
                f"  Elevation: +{stats.total_elevation_gain_m:.0f}m / "
                f"-{stats.total_elevation_loss_m:.0f}m"
            )

        # Geocode if requested
        if geocode:
            from gps_journey.core.processor import JourneyProcessor

            console.print("\n[blue]Geocoding locations...[/blue]")
            processor = JourneyProcessor(
                geocoding_enabled=True, geocoding_cache_path=Path(".geocode_cache.json")
            )
            journey = processor.process(gpx_file)

            if journey.start_location:
                console.print(f"[green]✓[/green] Start: {journey.start_location}")
            if journey.end_location:
                console.print(f"[green]✓[/green] End: {journey.end_location}")

        # Photos if requested
        if photos:
            if not album:
                console.print("[red]Error:[/red] --album required when using --photos")
                raise typer.Exit(1)
            console.print("\n[yellow]Google Photos functionality coming in Phase 2[/yellow]")

        # Map generation if requested
        if map_output:
            console.print("\n[yellow]Map generation coming soon[/yellow]")

        # Hugo markdown generation
        if output:
            from gps_journey.hugo.generator import HugoGenerator

            console.print("\n[blue]Generating Hugo markdown...[/blue]")
            generator = HugoGenerator(static_dir=static_dir)
            output_path = generator.generate(journey, slug=output.stem if output else None)
            console.print(f"[green]✓[/green] Generated: {output_path}")

        console.print("\n[bold green]✓ Processing complete[/bold green]")

    except Exception as e:
        logger.exception("Processing failed")
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)  # noqa: B904


@app.command()
def validate(
    gpx_file: Path = typer.Argument(..., help="Path to GPX file", exists=True),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Validate a GPX file."""
    setup_logging(verbose)

    try:
        parser = GPXParser()
        journey = parser.parse(gpx_file)

        console.print("[green]✓ GPX file is valid[/green]")
        console.print(f"  Waypoints: {len(journey.waypoints)}")
        console.print(f"  Start: {journey.start_date}")
        console.print(f"  End: {journey.end_date}")
        console.print(f"  Duration: {journey.duration_days} days")

    except Exception as e:
        console.print(f"[red]✗ GPX file is invalid:[/red] {e}")
        raise typer.Exit(1)  # noqa: B904


@app.command()
def export_metadata(
    journey_id: str = typer.Argument(..., help="Journey ID (e.g., sample-trip-2030-01)"),
    output: Path = typer.Option("journey.json", "-o", "--output", help="Output JSON file"),  # noqa: B008
    hugo_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--hugo-dir",
        help=(
            "Hugo content directory (default: HUGO_CONTENT_PATH in the environment, "
            "or HUGO__CONTENT_PATH in .env; else ./output/journeys)"
        ),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Export journey metadata for video pipeline integration."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    try:
        from gps_journey.export.journey_exporter import JourneyExporter

        # Determine Hugo directory
        if hugo_dir is None:
            # Configured content path (see HugoConfig), else a directory under the cwd.
            # Only the Hugo section is read, and only when --hugo-dir is absent.
            from gps_journey.config import HugoConfig, load_hugo_config

            fallback = Path("./output/journeys")
            try:
                hugo_dir = load_hugo_config().content_path or fallback
            except (ValueError, OSError) as exc:
                # Settings in the environment or a .env that this command cannot use
                # must not abort it; fall back to the process environment alone.
                logger.warning("Ignoring unreadable Hugo settings (%s)", type(exc).__name__)
                hugo_dir = HugoConfig().content_path or fallback

        # Try to find journey markdown file
        journey_md = hugo_dir / f"{journey_id}-enhanced.md"
        if not journey_md.exists():
            journey_md = hugo_dir / f"{journey_id}.md"

        if not journey_md.exists():
            console.print(f"[red]Error:[/red] Journey not found: {journey_id}")
            console.print(f"  Looked in: {hugo_dir}")
            console.print(f"  Tried: {journey_id}-enhanced.md, {journey_id}.md")
            raise typer.Exit(1)

        console.print(f"[blue]Exporting metadata for:[/blue] {journey_id}")
        console.print(f"  Source: {journey_md}")

        # Export metadata
        exporter = JourneyExporter()
        metadata = exporter.export_metadata(journey_md, output)

        # Display summary
        console.print("\n[green]✓ Exported metadata[/green]")
        console.print(f"  Route: {metadata['start_location']} → {metadata['end_location']}")
        console.print(f"  Distance: {metadata['total_distance_km']:.1f} km")
        console.print(f"  Duration: {metadata['duration_days']} days")
        if metadata["highlights"]:
            console.print(f"  Highlights: {', '.join(metadata['highlights'][:3])}")
        console.print(f"  Output: {output}")

    except Exception as e:
        logger.exception("Export failed")
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)  # noqa: B904


@app.command()
def version() -> None:
    """Show version information."""
    from gps_journey import __version__

    console.print(f"GPS Journey Service v{__version__}")


def main() -> None:
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
