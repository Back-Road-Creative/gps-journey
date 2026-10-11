"""
TDD Tests for Daily Processing Logic.

These tests define the expected behavior of generate_daily_breakdowns()
before implementation.
"""

from datetime import date, datetime, timedelta

import pytest

from gps_journey.core.models import DayStatistics, Journey, Location, Photo, Waypoint
from gps_journey.core.processor import JourneyProcessor


class TestDailyBreakdownGeneration:
    """Test generate_daily_breakdowns() method."""

    def test_single_day_journey(self):
        """Test journey that occurs within a single day."""
        # Create waypoints for a single day (synthetic window)
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 10, 10, 0, 0),
                elevation=2500.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 10, 12, 0, 0),
                elevation=2600.0,
            ),
            Waypoint(
                latitude=55.2,
                longitude=-7.2,
                timestamp=datetime(2031, 5, 10, 15, 0, 0),
                elevation=2700.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 10, 10, 0, 0),
            end_date=datetime(2031, 5, 10, 15, 0, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        assert len(result.daily_breakdowns) == 1
        assert result.daily_breakdowns[0].statistics.day_number == 1
        assert result.daily_breakdowns[0].statistics.date == date(2031, 5, 10)
        assert len(result.daily_breakdowns[0].waypoints) == 3

    def test_multi_day_journey_split(self):
        """Test journey spanning multiple days gets split correctly."""
        # Create waypoints for 3 days
        waypoints = [
            # Day 1
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                elevation=200.0,
            ),
            # Day 2
            Waypoint(
                latitude=55.2,
                longitude=-7.2,
                timestamp=datetime(2031, 5, 16, 8, 0, 0),
                elevation=150.0,
            ),
            Waypoint(
                latitude=55.3,
                longitude=-7.3,
                timestamp=datetime(2031, 5, 16, 18, 0, 0),
                elevation=250.0,
            ),
            # Day 3
            Waypoint(
                latitude=55.4,
                longitude=-7.4,
                timestamp=datetime(2031, 5, 17, 9, 0, 0),
                elevation=300.0,
            ),
            Waypoint(
                latitude=55.5,
                longitude=-7.5,
                timestamp=datetime(2031, 5, 17, 19, 0, 0),
                elevation=350.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 17, 19, 0, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        assert len(result.daily_breakdowns) == 3
        assert result.daily_breakdowns[0].statistics.day_number == 1
        assert result.daily_breakdowns[1].statistics.day_number == 2
        assert result.daily_breakdowns[2].statistics.day_number == 3
        assert result.daily_breakdowns[0].statistics.date == date(2031, 5, 15)
        assert result.daily_breakdowns[1].statistics.date == date(2031, 5, 16)
        assert result.daily_breakdowns[2].statistics.date == date(2031, 5, 17)

    def test_midnight_crossing_waypoints(self):
        """Test waypoints that cross midnight are grouped correctly."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 23, 50, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 23, 55, 0),
                elevation=120.0,
            ),
            Waypoint(
                latitude=55.2,
                longitude=-7.2,
                timestamp=datetime(2031, 5, 16, 0, 5, 0),  # Next day
                elevation=130.0,
            ),
            Waypoint(
                latitude=55.3,
                longitude=-7.3,
                timestamp=datetime(2031, 5, 16, 0, 10, 0),  # Next day
                elevation=140.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 23, 50, 0),
            end_date=datetime(2031, 5, 16, 0, 10, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Should split into 2 days
        assert len(result.daily_breakdowns) == 2
        # Day 1 should have 2 waypoints (23:50, 23:55)
        assert len(result.daily_breakdowns[0].waypoints) == 2
        # Day 2 should have 2 waypoints (00:05, 00:10)
        assert len(result.daily_breakdowns[1].waypoints) == 2

    def test_distance_calculation_per_day(self):
        """Test that distance is calculated correctly for each day."""
        waypoints = [
            # Day 1: Two waypoints far apart
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=56.0,
                longitude=-8.0,
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                elevation=200.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 15, 17, 0, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Distance should be > 0 (rough approximation: ~140km)
        assert result.daily_breakdowns[0].statistics.distance_km > 0
        assert result.daily_breakdowns[0].statistics.distance_km < 200  # Sanity check

    def test_elevation_gain_loss_per_day(self):
        """Test elevation gain and loss calculation per day."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=500.0,  # +400m gain
            ),
            Waypoint(
                latitude=55.2,
                longitude=-7.2,
                timestamp=datetime(2031, 5, 15, 14, 0, 0),
                elevation=200.0,  # -300m loss
            ),
            Waypoint(
                latitude=55.3,
                longitude=-7.3,
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                elevation=350.0,  # +150m gain
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 15, 17, 0, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Total elevation gain: 400 + 150 = 550m
        # Total elevation loss: 300m
        assert result.daily_breakdowns[0].statistics.elevation_gain_m == pytest.approx(
            550.0, abs=1.0
        )
        assert result.daily_breakdowns[0].statistics.elevation_loss_m == pytest.approx(
            300.0, abs=1.0
        )

    def test_photo_matching_to_days(self):
        """Test photos are matched to correct days by timestamp."""
        waypoints = [
            # Day 1
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=100.0,
            ),
            # Day 2
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 16, 10, 0, 0),
                elevation=150.0,
            ),
        ]

        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 30, 0),  # Day 1
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 14, 0, 0),  # Day 1
            ),
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 16, 11, 0, 0),  # Day 2
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 10, 0, 0),
            end_date=datetime(2031, 5, 16, 10, 0, 0),
            waypoints=tuple(waypoints),
            photos=tuple(photos),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Day 1 should have 2 photos
        assert result.daily_breakdowns[0].statistics.photo_count == 2
        # Day 2 should have 1 photo
        assert result.daily_breakdowns[1].statistics.photo_count == 1

    def test_auto_summary_generation(self):
        """Test auto-generated narrative summary format."""
        start_loc = Location(
            latitude=55.0,
            longitude=-7.0,
            name="Westmere",
            county="County Tarrow",
        )
        end_loc = Location(
            latitude=55.2,
            longitude=-7.5,
            name="Harbourview Head",
            county="County Tarrow",
        )

        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 0, 0),
                elevation=100.0,
                location=start_loc,
            ),
            Waypoint(
                latitude=55.2,
                longitude=-7.5,
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                elevation=200.0,
                location=end_loc,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 15, 17, 0, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Narrative should contain start and end locations
        narrative = result.daily_breakdowns[0].narrative
        assert "Westmere" in narrative or "westmere" in narrative.lower()
        assert "Harbourview" in narrative or "harbourview" in narrative.lower()
        # Should contain distance in km
        assert "km" in narrative.lower()

    def test_duration_hours_calculation(self):
        """Test duration in hours is calculated correctly."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 0, 0),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 15, 30, 0),  # 8 hours 30 minutes later
                elevation=200.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 15, 15, 30, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        # Duration should be ~8.5 hours
        assert result.daily_breakdowns[0].statistics.duration_hours == pytest.approx(8.5, abs=0.1)

    def test_waypoint_count_per_day(self):
        """Test waypoint count is accurate for each day."""
        waypoints = [
            Waypoint(
                latitude=55.0 + i * 0.01,
                longitude=-7.0 + i * 0.01,
                timestamp=datetime(2031, 5, 15, 7, 0, 0) + timedelta(minutes=i * 10),
                elevation=100.0,
            )
            for i in range(50)  # 50 waypoints in one day
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 0, 0),
            end_date=datetime(2031, 5, 15, 15, 10, 0),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        assert result.daily_breakdowns[0].statistics.waypoint_count == 50

    def test_empty_photos_handled(self):
        """Test that journey with no photos is handled gracefully."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                elevation=100.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 10, 0, 0),
            end_date=datetime(2031, 5, 15, 17, 0, 0),
            waypoints=tuple(waypoints),
            photos=(),  # Empty photos
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        assert result.daily_breakdowns[0].statistics.photo_count == 0
        assert len(result.daily_breakdowns[0].photos) == 0

    def test_start_end_times_per_day(self):
        """Test that start and end times are captured correctly."""
        waypoints = [
            Waypoint(
                latitude=55.0,
                longitude=-7.0,
                timestamp=datetime(2031, 5, 15, 7, 15, 30),
                elevation=100.0,
            ),
            Waypoint(
                latitude=55.1,
                longitude=-7.1,
                timestamp=datetime(2031, 5, 15, 12, 0, 0),
                elevation=150.0,
            ),
            Waypoint(
                latitude=55.2,
                longitude=-7.2,
                timestamp=datetime(2031, 5, 15, 18, 45, 20),
                elevation=200.0,
            ),
        ]

        journey = Journey(
            start_date=datetime(2031, 5, 15, 7, 15, 30),
            end_date=datetime(2031, 5, 15, 18, 45, 20),
            waypoints=tuple(waypoints),
        )

        processor = JourneyProcessor()
        result = processor.generate_daily_breakdowns(journey)

        stats = result.daily_breakdowns[0].statistics
        assert stats.start_time == datetime(2031, 5, 15, 7, 15, 30)
        assert stats.end_time == datetime(2031, 5, 15, 18, 45, 20)
