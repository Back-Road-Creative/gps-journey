"""GPX file export functionality."""

import logging
from pathlib import Path

import gpxpy
import gpxpy.gpx

from gps_journey.core.models import Waypoint

logger = logging.getLogger(__name__)


class GPXExporter:
    """Export waypoints to GPX format for downloads."""

    def export_day_gpx(
        self, waypoints: list[Waypoint], day_number: int, journey_slug: str, output_dir: Path
    ) -> str:
        """
        Export single day's waypoints to GPX file.

        Args:
            waypoints: List of waypoints for the day
            day_number: Day number (1-indexed)
            journey_slug: Journey slug for filename
            output_dir: Directory to save GPX file

        Returns:
            Relative path for Hugo: /gpx/{slug}-day{N}.gpx

        Raises:
            ValueError: If waypoints list is empty
        """
        if not waypoints:
            raise ValueError("Cannot export GPX: no waypoints provided")

        # Create GPX object
        gpx = gpxpy.gpx.GPX()

        # Create track
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx_track.name = f"Day {day_number}"
        gpx.tracks.append(gpx_track)

        # Create segment
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        gpx_track.segments.append(gpx_segment)

        # Add waypoints to segment
        for waypoint in waypoints:
            gpx_point = gpxpy.gpx.GPXTrackPoint(
                latitude=waypoint.latitude,
                longitude=waypoint.longitude,
                elevation=waypoint.elevation,
                time=waypoint.timestamp,
            )
            gpx_segment.points.append(gpx_point)

        # Generate filename
        filename = f"{journey_slug}-day{day_number}.gpx"
        output_path = Path(output_dir) / filename

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write GPX file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(gpx.to_xml())

        logger.info(f"Exported GPX: {output_path} ({len(waypoints)} points)")

        # Return relative path for Hugo
        return f"/gpx/{filename}"
