"""Hugo markdown generator for journey content."""

import json
import logging
from pathlib import Path

import yaml

from gps_journey.core.models import Journey
from gps_journey.narrative.simple_generator import filter_locations

logger = logging.getLogger(__name__)


class HugoGenerator:
    """
    Generate Hugo-compatible markdown files for journeys.

    Outputs markdown files with YAML frontmatter matching the
    journey archetype.
    """

    def __init__(self, output_dir: Path | None = None, static_dir: Path | None = None):
        """
        Initialize Hugo generator.

        Args:
            output_dir: Output directory for generated files
            static_dir: Optional Hugo ``static`` directory. When set, photo
                mapping files are looked up under it first.
        """
        self.output_dir = Path(output_dir) if output_dir else Path(".")
        self.static_dir = Path(static_dir) if static_dir else None
        self.photo_mapping: dict[str, str] | None = None

    def _load_photo_mapping(self, gallery_path: str) -> dict[str, str]:
        """
        Load photo mapping from gallery directory.

        Args:
            gallery_path: Gallery path like "images/journeys/sample-trip-2030-01"

        Returns:
            Dict mapping original filenames to sequential filenames
        """
        # gallery_path: "images/journeys/sample-trip-2030-01". Look under the
        # configured static directory first (if any), then relative to the cwd.
        mapping_locations = []
        if self.static_dir is not None:
            mapping_locations.append(self.static_dir / gallery_path / "photo_mapping.json")
        mapping_locations.append(Path(gallery_path) / "photo_mapping.json")

        for mapping_file in mapping_locations:
            if mapping_file.exists():
                try:
                    with open(mapping_file) as f:
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load photo mapping from {mapping_file}: {e}")

        logger.debug(f"No photo mapping found for {gallery_path}")
        return {}

    def generate(
        self,
        journey: Journey,
        title: str | None = None,
        slug: str | None = None,
        journey_id: str | None = None,
        gallery_path: str | None = None,
    ) -> str:
        """
        Generate Hugo markdown file for a journey.

        Args:
            journey: Journey object to convert
            title: Optional custom title (default: auto-generated)
            slug: Optional custom slug for filename
            journey_id: Journey identifier for featured image (e.g., 'sample-trip-2030-01')
            gallery_path: Path to photo gallery (e.g., 'images/journeys/sample-trip-2030-01')

        Returns:
            Path to generated markdown file
        """
        # Generate title and slug
        if not title:
            title = self._generate_title(journey)
        if not slug:
            slug = self._generate_slug(title)

        # Use journey_id for featured image if provided, otherwise fall back to slug
        featured_image_slug = journey_id if journey_id else slug

        # Load photo mapping if gallery_path provided
        if gallery_path:
            self.photo_mapping = self._load_photo_mapping(gallery_path)
        else:
            self.photo_mapping = {}

        # Build frontmatter
        frontmatter = self._build_frontmatter(journey, title, featured_image_slug, gallery_path)

        # Build markdown body
        body = self._build_body(journey)

        # Combine into full markdown
        markdown = self._format_markdown(frontmatter, body)

        # Write to file
        output_file = self.output_dir / f"{slug}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)

        logger.info(f"Generated Hugo markdown: {output_file}")
        return str(output_file)

    def _generate_title(self, journey: Journey) -> str:
        """Generate a title for the journey."""
        if journey.title:
            return journey.title

        # Use locations if available
        if journey.start_location and journey.end_location:
            start = journey.start_location.city or journey.start_location.state
            end = journey.end_location.city or journey.end_location.state

            if start and end and start != end:
                return f"{start} to {end} Road Trip"
            elif start:
                return f"{start} Journey"

        # Fall back to date-based title
        return f"Journey {journey.start_date.strftime('%B %Y')}"

    def _generate_slug(self, title: str) -> str:
        """Generate URL-friendly slug from title."""
        slug = title.lower()
        slug = slug.replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        return slug

    def _build_frontmatter(
        self,
        journey: Journey,
        title: str,
        featured_image_slug: str | None = None,
        gallery_path: str | None = None,
    ) -> dict:
        """Build YAML frontmatter matching journey archetype.

        Args:
            journey: Journey object
            title: Journey title
            featured_image_slug: Slug for featured image path (e.g., 'sample-trip-2030-01')
            gallery_path: Path to photo gallery (e.g., 'images/journeys/sample-trip-2030-01')
        """
        # Use provided slug or generate from title
        slug = featured_image_slug if featured_image_slug else self._generate_slug(title)

        frontmatter = {
            "title": title,
            "date": journey.start_date.strftime("%Y-%m-%d"),
            "author": "Go Move Shift",
            "draft": False,  # Published by default
            "categories": ["Journeys"],
            "tags": [],
            "description": journey.description or f"A {journey.duration_days}-day journey",
            "summary": f"A {journey.duration_days}-day journey covering "
            f"{journey.statistics.total_distance_km:.0f} km"
            if journey.statistics
            else "",
            "featured_image": f"images/featured/{slug}.jpg",
            "featured_image_alt": title,
        }

        # Add gallery_path for photo display
        if gallery_path:
            frontmatter["gallery_path"] = gallery_path

        # Add location data
        if journey.start_location:
            frontmatter["location"] = {
                "name": journey.start_location.city or journey.start_location.state,
                "country": journey.start_location.country,
                "coordinates": {
                    "lat": round(journey.start_location.latitude, 4),
                    "lon": round(journey.start_location.longitude, 4),
                },
            }

        # Add trip details
        frontmatter["trip"] = {
            "start_date": journey.start_date.strftime("%Y-%m-%d"),
            "end_date": journey.end_date.strftime("%Y-%m-%d"),
            "duration_days": journey.duration_days,
        }

        if journey.statistics:
            frontmatter["trip"]["distance_km"] = round(journey.statistics.total_distance_km, 1)

        # Add daily breakdowns if available
        if journey.daily_breakdowns:
            frontmatter["days"] = [
                {
                    "day_number": day.statistics.day_number,
                    "date": day.statistics.date.isoformat(),
                    "day_of_week": day.statistics.date.strftime("%A"),
                    "summary": day.narrative,
                    "statistics": {
                        "distance_km": round(day.statistics.distance_km, 1),
                        "duration_hours": round(day.statistics.duration_hours, 1),
                        "elevation_gain_m": int(day.statistics.elevation_gain_m),
                        "elevation_loss_m": int(day.statistics.elevation_loss_m),
                        "photo_count": day.statistics.photo_count,
                    },
                    "locations": filter_locations(list(day.locations_visited))
                    if day.locations_visited
                    else [],
                    "map": day.map_file,
                    "gpx_download": day.gpx_file,
                    "photos": [
                        {
                            "location": self._normalize_location_name(group.location_name),
                            "photos": [
                                self.photo_mapping.get(photo.filename, photo.filename)
                                for photo in group.photos
                            ],
                        }
                        for group in day.photo_groups
                        # Include ALL photo groups - don't filter by location name
                        # Photos should always display, even with coordinate-only locations
                    ]
                    if day.photo_groups
                    else [],
                }
                for day in journey.daily_breakdowns
            ]

        # Add display options
        frontmatter["featured"] = False
        frontmatter["toc"] = True

        return frontmatter

    def _build_body(self, journey: Journey) -> str:
        """Build markdown body content with journey overview."""
        from gps_journey.narrative.simple_generator import SimpleNarrativeGenerator

        lines = ["## Journey Overview", ""]

        # Generate overview narrative if we have data
        if journey.statistics and journey.start_location and journey.end_location:
            generator = SimpleNarrativeGenerator()

            # Get location names
            start_name = (
                journey.start_location.city
                or journey.start_location.state
                or str(journey.start_location)
            )
            end_name = (
                journey.end_location.city or journey.end_location.state or str(journey.end_location)
            )

            # Count total photos
            total_photos = len(journey.photos)

            overview = generator.generate_journey_overview(
                title=journey.title or "Journey",
                start_date=journey.start_date,
                end_date=journey.end_date,
                start_location=start_name,
                end_location=end_name,
                total_distance_km=journey.statistics.total_distance_km,
                duration_days=journey.duration_days,
                total_photos=total_photos,
            )

            lines.append(overview)
            lines.append("")
        elif journey.start_location and journey.end_location:
            # Fallback without statistics
            start = str(journey.start_location)
            end = str(journey.end_location)
            lines.append(f"Traveling from **{start}** to **{end}**.")
            lines.append("")

        # Add statistics if available
        if journey.statistics:
            stats = journey.statistics
            lines.append("### Journey Statistics")
            lines.append("")
            lines.append(
                f"- **Distance:** {stats.total_distance_km:.1f} km "
                f"({stats.total_distance_miles:.1f} miles)"
            )
            lines.append(f"- **Duration:** {journey.duration_days} days")
            lines.append(f"- **Elevation Gain:** {stats.total_elevation_gain_m:.0f} m")
            lines.append(f"- **Average Speed:** {stats.average_speed_kmh:.1f} km/h")
            lines.append("")

        lines.append("<!--more-->")
        lines.append("")

        return "\n".join(lines)

    def _normalize_location_name(self, name: str) -> str:
        """
        Normalize location name for display.

        Converts coordinate-only names and the non-GPS "Unknown Location"
        sentinel to a neutral caption, so neither placeholder ships to the
        public site as if it were a real place. Photos still display; only
        the label is neutralized.
        """
        import re

        from gps_journey.photos.grouper import UNKNOWN_LOCATION

        # Non-GPS photo group: don't publish the "Unknown Location" placeholder
        if name == UNKNOWN_LOCATION:
            return "Photos"

        # Match coordinate-only patterns like "51.2500, -7.4250"
        coord_pattern = re.compile(r"^-?\d+\.\d+,\s*-?\d+\.\d+$")

        if coord_pattern.match(name):
            return "Photos (Location)"

        return name

    def _format_markdown(self, frontmatter: dict, body: str) -> str:
        """Format frontmatter and body into complete markdown."""
        # Convert frontmatter to YAML
        yaml_str = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # Combine with body
        markdown = f"---\n{yaml_str}---\n\n{body}"

        return markdown
