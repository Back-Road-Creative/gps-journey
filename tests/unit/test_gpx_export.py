"""
TDD Tests for GPX Export.

Tests for exporting waypoints to GPX format for daily downloads.
"""

from datetime import datetime
from pathlib import Path

import gpxpy
import pytest

from gps_journey.core.gpx_exporter import GPXExporter
from gps_journey.core.models import Waypoint


class TestGPXExporter:
    """Test GPXExporter class."""

    def test_export_day_gpx_creates_file(self, tmp_path):
        """Test that GPX file is created."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 11, 0, 0),
                elevation=150.0,
            ),
        ]

        exporter = GPXExporter()
        result_path = exporter.export_day_gpx(
            waypoints=waypoints, day_number=1, journey_slug="test-journey", output_dir=tmp_path
        )

        # Check file was created
        expected_file = tmp_path / "test-journey-day1.gpx"
        assert expected_file.exists()
        assert result_path == "/gpx/test-journey-day1.gpx"

    def test_export_day_gpx_valid_xml(self, tmp_path):
        """Test that exported GPX is valid XML that can be re-parsed."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 11, 0, 0),
                elevation=150.0,
            ),
        ]

        exporter = GPXExporter()
        exporter.export_day_gpx(
            waypoints=waypoints, day_number=1, journey_slug="test-journey", output_dir=tmp_path
        )

        # Try to parse the generated file
        gpx_file = tmp_path / "test-journey-day1.gpx"
        with open(gpx_file) as f:
            gpx = gpxpy.parse(f)

        # Should have parsed successfully
        assert gpx is not None

    def test_export_day_gpx_waypoint_count(self, tmp_path):
        """Test that all waypoints are included in GPX."""
        waypoints = [
            Waypoint(
                latitude=55.0 + i * 0.1,
                longitude=-7.0 + i * 0.1,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=100.0 + i * 10,
            )
            for i in range(10)
        ]

        exporter = GPXExporter()
        exporter.export_day_gpx(
            waypoints=waypoints, day_number=1, journey_slug="test-journey", output_dir=tmp_path
        )

        # Parse and count waypoints
        gpx_file = tmp_path / "test-journey-day1.gpx"
        with open(gpx_file) as f:
            gpx = gpxpy.parse(f)

        # Count track points
        total_points = sum(
            len(segment.points) for track in gpx.tracks for segment in track.segments
        )

        assert total_points == 10

    def test_export_day_gpx_preserves_timestamps(self, tmp_path):
        """Test that timestamps are preserved in GPX."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 30, 45),
                elevation=100.0,
            ),
        ]

        exporter = GPXExporter()
        exporter.export_day_gpx(
            waypoints=waypoints, day_number=1, journey_slug="test-journey", output_dir=tmp_path
        )

        # Parse and check timestamp
        gpx_file = tmp_path / "test-journey-day1.gpx"
        with open(gpx_file) as f:
            gpx = gpxpy.parse(f)

        point = gpx.tracks[0].segments[0].points[0]
        assert point.time == datetime(2031, 5, 15, 10, 30, 45)

    def test_export_day_gpx_preserves_elevation(self, tmp_path):
        """Test that elevations are preserved in GPX."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=123.45,
            ),
        ]

        exporter = GPXExporter()
        exporter.export_day_gpx(
            waypoints=waypoints, day_number=1, journey_slug="test-journey", output_dir=tmp_path
        )

        # Parse and check elevation
        gpx_file = tmp_path / "test-journey-day1.gpx"
        with open(gpx_file) as f:
            gpx = gpxpy.parse(f)

        point = gpx.tracks[0].segments[0].points[0]
        assert point.elevation == pytest.approx(123.45, abs=0.01)

    def test_export_day_gpx_file_naming(self, tmp_path):
        """Test correct file naming convention."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
            ),
        ]

        exporter = GPXExporter()

        # Day 1
        result = exporter.export_day_gpx(
            waypoints=waypoints,
            day_number=1,
            journey_slug="sample-trip-2031-05",
            output_dir=tmp_path,
        )
        assert result == "/gpx/sample-trip-2031-05-day1.gpx"
        assert (tmp_path / "sample-trip-2031-05-day1.gpx").exists()

        # Day 13
        result = exporter.export_day_gpx(
            waypoints=waypoints,
            day_number=13,
            journey_slug="sample-trip-2031-05",
            output_dir=tmp_path,
        )
        assert result == "/gpx/sample-trip-2031-05-day13.gpx"
        assert (tmp_path / "sample-trip-2031-05-day13.gpx").exists()

    def test_export_day_gpx_empty_waypoints(self, tmp_path):
        """Test handling of empty waypoint list."""
        exporter = GPXExporter()

        with pytest.raises(ValueError, match="Cannot export GPX.*no waypoints"):  # noqa: RUF043
            exporter.export_day_gpx(
                waypoints=[], day_number=1, journey_slug="test", output_dir=tmp_path
            )
