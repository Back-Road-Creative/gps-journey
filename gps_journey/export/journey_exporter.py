"""
Journey Metadata Exporter.

Exports journey data from Hugo markdown files for use in video pipeline.
"""

import json
import re
from pathlib import Path


class JourneyExporter:
    """
    Export journey metadata from Hugo markdown files.

    Parses YAML frontmatter and extracts key information needed for
    downstream SEO and content tooling.
    """

    def export_metadata(self, journey_md_path: Path, output_json_path: Path) -> dict:
        """
        Export journey metadata from Hugo markdown to JSON.

        Args:
            journey_md_path: Path to journey markdown file
            output_json_path: Where to save JSON output

        Returns:
            Dict with journey metadata

        Raises:
            FileNotFoundError: If markdown file doesn't exist
            ValueError: If markdown file is malformed
        """
        if not journey_md_path.exists():
            raise FileNotFoundError(f"Journey markdown not found: {journey_md_path}")

        # Parse markdown file
        frontmatter, content = self._parse_hugo_markdown(journey_md_path)

        # Extract metadata
        metadata = self._extract_metadata(frontmatter, content)

        # Save to JSON
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata

    def _parse_hugo_markdown(self, md_path: Path) -> tuple[dict, str]:
        """
        Parse Hugo markdown file into frontmatter and content.

        Args:
            md_path: Path to markdown file

        Returns:
            Tuple of (frontmatter dict, content string)
        """
        with open(md_path, encoding="utf-8") as f:
            content = f.read()

        # Split frontmatter from content
        # Hugo frontmatter is between --- delimiters
        parts = content.split("---", 2)

        if len(parts) < 3:
            raise ValueError(f"Malformed markdown file: {md_path}")

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        # Parse YAML frontmatter
        try:
            import yaml

            frontmatter = yaml.safe_load(frontmatter_text)
        except ImportError:
            # Fallback: simple key-value parsing if PyYAML not available
            frontmatter = self._parse_yaml_simple(frontmatter_text)

        return frontmatter, body

    def _parse_yaml_simple(self, yaml_text: str) -> dict:
        """Simple YAML parser fallback (basic key:value only)."""
        result = {}
        for line in yaml_text.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                result[key] = value
        return result

    def _extract_metadata(self, frontmatter: dict, content: str) -> dict:
        """
        Extract key metadata from frontmatter and content.

        Args:
            frontmatter: Parsed YAML frontmatter
            content: Markdown body content

        Returns:
            Dict with standardized metadata
        """
        # Extract journey ID from title or date
        journey_id = self._generate_journey_id(frontmatter)

        # Extract location data
        start_location = self._extract_start_location(frontmatter)
        end_location = self._extract_end_location(frontmatter)

        # Extract highlights (locations from days)
        highlights = self._extract_highlights(frontmatter)

        # Get distance
        total_distance_km = self._extract_distance(frontmatter)

        # Get country
        country = self._extract_country(frontmatter)

        # Get date range
        start_date, end_date = self._extract_date_range(frontmatter)

        # Build description
        description = self._build_description(
            start_location, end_location, total_distance_km, highlights, start_date, end_date
        )

        # Compile metadata
        metadata = {
            "journey_id": journey_id,
            "title": frontmatter.get("title", ""),
            "date": frontmatter.get("date", ""),
            "start_location": start_location,
            "end_location": end_location,
            "highlights": highlights,
            "total_distance_km": total_distance_km,
            "country": country,
            "description": description,
            "start_date": start_date,
            "end_date": end_date,
            "duration_days": self._calculate_duration_days(frontmatter),
            "featured_image": frontmatter.get("featured_image", ""),
            "summary": frontmatter.get("summary", ""),
            "tags": frontmatter.get("tags", []),
        }

        return metadata

    def _generate_journey_id(self, frontmatter: dict) -> str:
        """Generate journey ID from title or date."""
        # Try to extract from title if it follows pattern "Country YYYY-MM"
        title = frontmatter.get("title", "")

        # Check for date pattern in title
        match = re.search(r"(\w+).*?(\d{4})", title)
        if match:
            country = match.group(1).lower()
            year = match.group(2)

            # Try to get month from date field
            date_str = frontmatter.get("date", "")
            month_match = re.search(r"\d{4}-(\d{2})", str(date_str))
            if month_match:
                month = month_match.group(1)
                return f"{country}-{year}-{month}"

        # Fallback: use date field
        date = frontmatter.get("date", "")
        if date:
            # Convert date to YYYY-MM format
            date_match = re.search(r"(\d{4})-(\d{2})", str(date))
            if date_match:
                return f"journey-{date_match.group(1)}-{date_match.group(2)}"

        return "unknown-journey"

    def _extract_start_location(self, frontmatter: dict) -> str:
        """Extract starting location from first day."""
        days = frontmatter.get("days", [])
        if days and len(days) > 0:
            first_day = days[0]
            locations = first_day.get("locations", [])
            if locations:
                return locations[0]

        # Fallback to location.name if available
        location = frontmatter.get("location", {})
        if isinstance(location, dict):
            return location.get("name", "Unknown")

        return "Unknown"

    def _extract_end_location(self, frontmatter: dict) -> str:
        """Extract ending location from last day."""
        days = frontmatter.get("days", [])
        if days and len(days) > 0:
            last_day = days[-1]
            locations = last_day.get("locations", [])
            if locations:
                return locations[-1]

        return "Unknown"

    def _extract_highlights(self, frontmatter: dict) -> list[str]:
        """Extract interesting locations from all days."""
        highlights = set()
        days = frontmatter.get("days", [])

        # Collect unique locations from first 3 and last 3 days
        # (to get start and end highlights)
        for day in days[:3] + days[-3:]:
            locations = day.get("locations", [])
            # Take locations that look interesting (longer names, specific places)
            for loc in locations:
                if len(loc) > 10 and "," in loc:  # e.g., "Cloonlee, County Fairhaven"
                    # Just take the main place name
                    main_place = loc.split(",")[0].strip()
                    highlights.add(main_place)

        # Limit to 5 most interesting highlights
        return sorted(list(highlights))[:5]

    def _extract_distance(self, frontmatter: dict) -> float:
        """Extract total distance in kilometers."""
        trip = frontmatter.get("trip", {})
        if isinstance(trip, dict):
            distance = trip.get("distance_km", 0)
            if distance:
                return round(float(distance), 1)

        return 0.0

    def _extract_country(self, frontmatter: dict) -> str:
        """Return the journey's country from the ``location.country`` frontmatter.

        Requires the field. Inferring the country from title or location
        substrings is unsafe: place names repeat across countries (Clare MI and
        Fairhaven NY are US towns), so a substring match would export the wrong
        country. The producer (``hugo/generator.py``) always writes
        ``location.country``, so a missing field is a genuine defect: fail
        loudly rather than guess.
        """
        location = frontmatter.get("location", {})
        if isinstance(location, dict):
            country = location.get("country", "")
            if country:
                return country

        raise ValueError(
            "journey frontmatter is missing required 'location.country'; "
            "refusing to infer the country by title/location substring "
            "(place names repeat across countries, so a guess can be wrong). "
            "Set location.country in the journey markdown."
        )

    def _extract_date_range(self, frontmatter: dict) -> tuple[str, str]:
        """Extract start and end dates."""
        trip = frontmatter.get("trip", {})
        if isinstance(trip, dict):
            start = trip.get("start_date", "")
            end = trip.get("end_date", "")
            return str(start), str(end)

        # Fallback to main date field
        date = frontmatter.get("date", "")
        return str(date), str(date)

    def _calculate_duration_days(self, frontmatter: dict) -> int:
        """Calculate journey duration in days."""
        trip = frontmatter.get("trip", {})
        if isinstance(trip, dict):
            duration = trip.get("duration_days", 0)
            if duration:
                return int(duration)

        # Fallback: count days
        days = frontmatter.get("days", [])
        return len(days) if days else 1

    def _build_description(
        self,
        start: str,
        end: str,
        distance: float,
        highlights: list[str],
        start_date: str,
        end_date: str,
    ) -> str:
        """Build rich description from journey data."""
        parts = []

        if start and end:
            parts.append(f"Journey from {start} to {end}")

        if distance > 0:
            parts.append(f"covering {distance:.0f} kilometers")

        if highlights:
            parts.append(f"passing through {', '.join(highlights[:3])}")

        # No generic filler: an empty description is honest; filler asserts a
        # scenic-ness the data doesn't carry.
        return ". ".join(parts) + "." if parts else ""
