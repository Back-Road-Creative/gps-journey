"""
TDD Tests for Daily Breakdown Models.

These tests define the expected behavior of DayStatistics, PhotoGroup,
and DayBreakdown models before implementation.
"""

from datetime import date, datetime

import pytest

from gps_journey.core.models import (
    DayBreakdown,
    DayStatistics,
    Journey,
    Location,
    Photo,
    PhotoGroup,
    Waypoint,
)


class TestDayStatistics:
    """Test DayStatistics model."""

    def test_day_statistics_creation(self):
        """Test basic DayStatistics creation."""
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=10,
            waypoint_count=5432,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        assert stats.day_number == 1
        assert stats.date == date(2031, 5, 15)
        assert stats.distance_km == 150.0
        assert stats.duration_hours == 8.5
        assert stats.elevation_gain_m == 2400.0
        assert stats.photo_count == 10

    def test_day_statistics_with_locations(self):
        """Test DayStatistics with start and end locations."""
        start_loc = Location(
            latitude=55.0,
            longitude=-7.0,
            name="Westmere",
            county="County Tarrow",
            country="Ireland",
        )
        end_loc = Location(
            latitude=55.2,
            longitude=-7.5,
            name="Harbourview Head",
            county="County Tarrow",
            country="Ireland",
        )

        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=10,
            waypoint_count=5432,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
            start_location=start_loc,
            end_location=end_loc,
        )

        assert stats.start_location.name == "Westmere"
        assert stats.end_location.name == "Harbourview Head"

    def test_day_statistics_to_dict(self):
        """Test DayStatistics serialization to dict."""
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=10,
            waypoint_count=5432,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        result = stats.to_dict()

        assert isinstance(result, dict)
        assert result["day_number"] == 1
        assert result["date"] == "2031-05-15"
        assert result["distance_km"] == 150.0
        assert result["photo_count"] == 10

    def test_day_statistics_immutable(self):
        """Test that DayStatistics is immutable (frozen dataclass)."""
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=10,
            waypoint_count=5432,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        with pytest.raises(AttributeError):
            stats.distance_km = 200.0


class TestPhotoGroup:
    """Test PhotoGroup model."""

    def test_photo_group_creation(self):
        """Test basic PhotoGroup creation with multiple photos."""
        photo1 = Photo(
            filename="photo-001.jpg",
            timestamp=datetime(2031, 5, 15, 10, 40, 55),
            latitude=55.1234,
            longitude=-7.5678,
            camera="Apple iPhone X",
        )
        photo2 = Photo(
            filename="photo-002.jpg",
            timestamp=datetime(2031, 5, 15, 10, 45, 10),
            latitude=55.1235,
            longitude=-7.5679,
            camera="Apple iPhone X",
        )

        group = PhotoGroup(
            location_name="Harbourview Head Lighthouse",
            latitude=55.1234,
            longitude=-7.5678,
            photos=(photo1, photo2),
        )

        assert group.location_name == "Harbourview Head Lighthouse"
        assert len(group.photos) == 2
        assert group.photos[0].filename == "photo-001.jpg"

    def test_photo_group_to_dict(self):
        """Test PhotoGroup serialization to dict."""
        photo = Photo(
            filename="photo-001.jpg",
            timestamp=datetime(2031, 5, 15, 10, 40, 55),
            latitude=55.1234,
            longitude=-7.5678,
        )

        group = PhotoGroup(
            location_name="Harbourview Head",
            latitude=55.1234,
            longitude=-7.5678,
            photos=(photo,),
        )

        result = group.to_dict()

        assert isinstance(result, dict)
        assert result["location_name"] == "Harbourview Head"
        assert result["latitude"] == 55.1234
        assert len(result["photos"]) == 1

    def test_photo_group_immutable(self):
        """Test that PhotoGroup is immutable."""
        photo = Photo(
            filename="photo-001.jpg",
            timestamp=datetime(2031, 5, 15, 10, 40, 55),
        )

        group = PhotoGroup(
            location_name="Harbourview Head",
            latitude=55.1234,
            longitude=-7.5678,
            photos=(photo,),
        )

        with pytest.raises(AttributeError):
            group.location_name = "Different Location"


class TestDayBreakdown:
    """Test DayBreakdown model."""

    def test_day_breakdown_creation(self):
        """Test basic DayBreakdown creation with all components."""
        # Create statistics
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=2,
            waypoint_count=2,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        # Create waypoints
        waypoint1 = Waypoint(
            latitude=55.0,
            longitude=-7.0,
            timestamp=datetime(2031, 5, 15, 7, 0, 0),
            elevation=100.0,
        )
        waypoint2 = Waypoint(
            latitude=55.2,
            longitude=-7.5,
            timestamp=datetime(2031, 5, 15, 15, 30, 0),
            elevation=150.0,
        )

        # Create photos
        photo1 = Photo(
            filename="photo-001.jpg",
            timestamp=datetime(2031, 5, 15, 10, 40, 55),
        )
        photo2 = Photo(
            filename="photo-002.jpg",
            timestamp=datetime(2031, 5, 15, 14, 30, 0),
        )

        # Create photo group
        photo_group = PhotoGroup(
            location_name="Harbourview Head",
            latitude=55.1234,
            longitude=-7.5678,
            photos=(photo1, photo2),
        )

        # Create breakdown
        breakdown = DayBreakdown(
            statistics=stats,
            waypoints=(waypoint1, waypoint2),
            photos=(photo1, photo2),
            photo_groups=(photo_group,),
            locations_visited=("Westmere", "Harbourview Head", "Rosscarra"),
            narrative="Westmere to Harbourview Peninsula Circuit (150 km)",
            map_file="/maps/sample-trip-2031-05-day1.html",
            gpx_file="/gpx/sample-trip-2031-05-day1.gpx",
        )

        assert breakdown.statistics.day_number == 1
        assert len(breakdown.waypoints) == 2
        assert len(breakdown.photos) == 2
        assert len(breakdown.photo_groups) == 1
        assert len(breakdown.locations_visited) == 3
        assert "Westmere" in breakdown.narrative
        assert breakdown.map_file == "/maps/sample-trip-2031-05-day1.html"

    def test_day_breakdown_to_dict(self):
        """Test DayBreakdown serialization to dict."""
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=0,
            waypoint_count=0,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        breakdown = DayBreakdown(
            statistics=stats,
            waypoints=(),
            photos=(),
            photo_groups=(),
            locations_visited=("Westmere", "Harbourview Head"),
            narrative="Day 1 journey",
        )

        result = breakdown.to_dict()

        assert isinstance(result, dict)
        assert result["statistics"]["day_number"] == 1
        assert len(result["locations_visited"]) == 2
        assert result["narrative"] == "Day 1 journey"

    def test_day_breakdown_optional_fields(self):
        """Test DayBreakdown with optional map and GPX files."""
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=0,
            waypoint_count=0,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        # Without map and GPX
        breakdown = DayBreakdown(
            statistics=stats,
            waypoints=(),
            photos=(),
            photo_groups=(),
            locations_visited=(),
            narrative="Day 1",
        )

        assert breakdown.map_file is None
        assert breakdown.gpx_file is None


class TestJourneyWithDailyBreakdowns:
    """Test Journey model with daily_breakdowns field."""

    def test_journey_with_empty_daily_breakdowns(self):
        """Test Journey can be created with empty daily_breakdowns."""
        journey = Journey(
            start_date=datetime(2031, 5, 15),
            end_date=datetime(2031, 5, 27),
            waypoints=(),
            photos=(),
            daily_breakdowns=(),
        )

        assert journey.daily_breakdowns == ()

    def test_journey_with_daily_breakdowns(self):
        """Test Journey with populated daily_breakdowns."""
        # Create a day breakdown
        stats = DayStatistics(
            day_number=1,
            date=date(2031, 5, 15),
            distance_km=150.0,
            duration_hours=8.5,
            elevation_gain_m=2400.0,
            elevation_loss_m=2300.0,
            photo_count=0,
            waypoint_count=0,
            start_time=datetime(2031, 5, 15, 7, 0, 0),
            end_time=datetime(2031, 5, 15, 15, 30, 0),
        )

        breakdown = DayBreakdown(
            statistics=stats,
            waypoints=(),
            photos=(),
            photo_groups=(),
            locations_visited=("Westmere",),
            narrative="Day 1",
        )

        journey = Journey(
            start_date=datetime(2031, 5, 15),
            end_date=datetime(2031, 5, 27),
            waypoints=(),
            photos=(),
            daily_breakdowns=(breakdown,),
        )

        assert len(journey.daily_breakdowns) == 1
        assert journey.daily_breakdowns[0].statistics.day_number == 1
