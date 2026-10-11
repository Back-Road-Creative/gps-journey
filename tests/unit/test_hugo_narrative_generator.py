"""Characterization tests for gps_journey.hugo.narrative_generator.

These pin what FactualNarrativeGenerator produces today (the day-by-day markdown,
stop detection, elevation and distance maths) so a pure restyle of the module can be
shown to change nothing. Pure functions over hand-built waypoints: no files, no
network, no clock.
"""

from datetime import date, datetime, timedelta

import pytest

from gps_journey.core.models import Journey, Location, Waypoint
from gps_journey.hugo.narrative_generator import FactualNarrativeGenerator

BASE = datetime(2026, 3, 10, 8, 0)


def _wp(lat, lon, when, elevation=None, location=None):
    return Waypoint(
        latitude=lat, longitude=lon, timestamp=when, elevation=elevation, location=location
    )


def _track(*points):
    """Waypoints from (lat, lon, minutes after 08:00 UTC) tuples."""
    return [_wp(lat, lon, BASE + timedelta(minutes=minutes)) for lat, lon, minutes in points]


def _elevations(*values):
    return [
        _wp(10.0, 0.0, BASE + timedelta(minutes=minute), elevation=value)
        for minute, value in enumerate(values)
    ]


def _journey(*waypoints):
    return Journey(
        start_date=waypoints[0].timestamp, end_date=waypoints[-1].timestamp, waypoints=waypoints
    )


class FakeGeocoder:
    """Only ever stored by the generator; it must never be called."""


class TestInit:
    def test_geocoder_defaults_to_none(self):
        assert FactualNarrativeGenerator().geocoder is None

    def test_geocoder_is_stored(self):
        geocoder = FakeGeocoder()
        assert FactualNarrativeGenerator(geocoder).geocoder is geocoder


class TestGenerateDayByDay:
    def test_two_days_of_facts(self):
        start_village = Location(
            latitude=10.0, longitude=0.0, name="Start Village", country="Testland"
        )
        end_town = Location(latitude=10.2, longitude=0.0, city="End Town", country="Testland")
        journey = _journey(
            _wp(10.0, 0.0, datetime(2026, 3, 10, 8, 0), elevation=100.0, location=start_village),
            _wp(10.0, 0.0, datetime(2026, 3, 10, 8, 20), elevation=120.0),
            _wp(10.1, 0.0, datetime(2026, 3, 10, 9, 0), elevation=90.0),
            _wp(10.2, 0.0, datetime(2026, 3, 10, 10, 30), elevation=250.0, location=end_town),
            _wp(20.0, 0.0, datetime(2026, 3, 11, 7, 0)),
            _wp(20.5, 0.0, datetime(2026, 3, 11, 9, 0)),
        )

        text = FactualNarrativeGenerator().generate_day_by_day(journey)

        assert text.split("\n") == [
            "## Day-by-Day Route",
            "",
            "*GPS data only - no creative content or research*",
            "",
            "### Day 1: Tuesday, March 10, 2026",
            "",
            "**Departed:** 08:00 AM",
            "**From:** Start Village, Testland",
            "**Starting elevation:** 100 m",
            "",
            "**Route Statistics:**",
            "- Distance: 22.2 km",
            "- Duration: 2.5 hours",
            "- Waypoints: 4",
            "- Elevation gain: 180 m",
            "- Elevation loss: 30 m",
            "",
            "**Detected Stops:**",
            "1. 08:00 AM - 20 minutes at Start Village, Testland",
            "",
            "**Arrived:** 10:30 AM",
            "**At:** End Town, Testland",
            "**Ending elevation:** 250 m",
            "",
            "---",
            "",
            "### Day 2: Wednesday, March 11, 2026",
            "",
            "**Departed:** 07:00 AM",
            "**From:** 20.0000°, 0.0000°",
            "",
            "**Route Statistics:**",
            "- Distance: 55.6 km",
            "- Duration: 2.0 hours",
            "- Waypoints: 2",
            "",
            "**Arrived:** 09:00 AM",
            "**At:** 20.5000°, 0.0000°",
            "",
            "---",
            "",
        ]

    def test_times_and_days_are_local_to_the_waypoint_longitude(self):
        journey = _journey(
            _wp(45.0, -100.0, datetime(2026, 3, 11, 2, 30)),
            _wp(45.1, -100.0, datetime(2026, 3, 11, 4, 0)),
        )
        lines = FactualNarrativeGenerator().generate_day_by_day(journey).split("\n")
        assert "### Day 1: Tuesday, March 10, 2026" in lines
        assert "**Departed:** 07:30 PM" in lines
        assert "**Arrived:** 09:00 PM" in lines


class TestGroupByDay:
    def test_days_follow_longitude_local_time_not_utc(self):
        waypoints = (
            _wp(45.0, -100.0, datetime(2026, 3, 10, 22, 0)),
            _wp(45.0, -100.0, datetime(2026, 3, 11, 4, 0)),
            _wp(45.0, -100.0, datetime(2026, 3, 11, 8, 0)),
        )
        by_day = FactualNarrativeGenerator()._group_by_day(waypoints)
        assert {day.isoformat(): len(group) for day, group in by_day.items()} == {
            "2026-03-10": 2,
            "2026-03-11": 1,
        }


class TestFormatDay:
    def test_lists_five_stops_and_counts_the_rest(self):
        points = []
        for k in range(7):
            points.append((10.0 + 0.1 * k, 0.0, 30 * k))
            points.append((10.0 + 0.1 * k, 0.0, 30 * k + 6))
        waypoints = _track(*points)
        camp = Location(latitude=10.0, longitude=0.0, name="Camp One")
        waypoints[0] = _wp(10.0, 0.0, BASE, location=camp)

        lines = FactualNarrativeGenerator()._format_day(1, date(2026, 3, 10), waypoints)

        start = lines.index("**Detected Stops:**")
        assert lines[start : start + 8] == [
            "**Detected Stops:**",
            "1. 08:00 AM - 6 minutes at Camp One",
            "2. 08:30 AM - 6 minutes at 10.1000°, 0.0000°",
            "3. 09:00 AM - 6 minutes at 10.2000°, 0.0000°",
            "4. 09:30 AM - 6 minutes at 10.3000°, 0.0000°",
            "5. 10:00 AM - 6 minutes at 10.4000°, 0.0000°",
            "   *(+2 more stops)*",
            "",
        ]
        assert not any(line.startswith("6. ") for line in lines)


class TestElevationChange:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ((100.0, 120.0, 90.0, 250.0), (180.0, 30.0)),
            ((100.0, None, 200.0), (0.0, 0.0)),
            ((300.0, 200.0), (0.0, 100.0)),
            ((100.0, 100.0), (0.0, 0.0)),
            ((), (0.0, 0.0)),
            ((100.0,), (0.0, 0.0)),
        ],
    )
    def test_gain_and_loss(self, values, expected):
        generator = FactualNarrativeGenerator()
        assert generator._calculate_elevation_change(_elevations(*values)) == expected


class TestDetectStops:
    def test_stationary_run_becomes_one_stop_with_its_location(self):
        camp = Location(latitude=53.0, longitude=-7.8, name="Camp")
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 5), (53.0, -7.8, 10), (53.5, -7.8, 20))
        track[0] = _wp(53.0, -7.8, BASE, location=camp)
        stops = FactualNarrativeGenerator()._detect_stops(track)
        assert stops == [{"time": BASE, "duration": 10, "lat": 53.0, "lon": -7.8, "location": camp}]

    def test_stop_location_is_none_when_the_waypoint_has_none(self):
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 6), (53.5, -7.8, 20))
        stops = FactualNarrativeGenerator()._detect_stops(track)
        assert [(s["duration"], s["location"]) for s in stops] == [(6, None)]

    def test_five_minute_threshold(self):
        generator = FactualNarrativeGenerator()
        short = _track((53.0, -7.8, 0), (53.0, -7.8, 4), (53.5, -7.8, 20))
        exact = _track((53.0, -7.8, 0), (53.0, -7.8, 5), (53.5, -7.8, 20))
        assert generator._detect_stops(short) == []
        assert [s["duration"] for s in generator._detect_stops(exact)] == [5]

    def test_fifty_metre_threshold(self):
        generator = FactualNarrativeGenerator()
        near = _track((53.0, -7.8, 0), (53.0003, -7.8, 6), (53.5, -7.8, 20))  # about 33 m
        far = _track((53.0, -7.8, 0), (53.001, -7.8, 6), (53.5, -7.8, 20))  # about 111 m
        assert [s["duration"] for s in generator._detect_stops(near)] == [6]
        assert generator._detect_stops(far) == []

    def test_moving_track_has_no_stops(self):
        track = _track((53.0, -7.8, 0), (53.1, -7.8, 5), (53.2, -7.8, 10))
        assert FactualNarrativeGenerator()._detect_stops(track) == []

    def test_two_separate_stops(self):
        track = _track(
            (53.0, -7.8, 0),
            (53.0, -7.8, 10),
            (53.5, -7.8, 30),
            (54.0, -7.8, 40),
            (54.0, -7.8, 47),
            (55.0, -7.8, 60),
        )
        stops = FactualNarrativeGenerator()._detect_stops(track)
        assert [(s["lat"], s["duration"]) for s in stops] == [(53.0, 10), (54.0, 7)]


class TestDistance:
    def test_calculate_distance_needs_two_points(self):
        generator = FactualNarrativeGenerator()
        assert generator._calculate_distance([]) == 0.0
        assert generator._calculate_distance(_track((53.0, -7.8, 0))) == 0.0

    def test_calculate_distance_sums_the_legs(self):
        track = _track((0.0, 0.0, 0), (0.0, 1.0, 5), (1.0, 1.0, 10))
        distance = FactualNarrativeGenerator()._calculate_distance(track)
        assert distance == pytest.approx(222.3898, abs=1e-3)

    def test_haversine_one_degree_of_longitude_on_the_equator(self):
        generator = FactualNarrativeGenerator()
        assert generator._haversine_single(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.1949, abs=1e-3)

    def test_haversine_shrinks_with_latitude(self):
        generator = FactualNarrativeGenerator()
        assert generator._haversine_single(60.0, 0.0, 60.0, 1.0) == pytest.approx(55.5975, abs=1e-2)

    def test_haversine_same_point_is_zero_and_the_result_is_symmetric(self):
        generator = FactualNarrativeGenerator()
        assert generator._haversine_single(53.0, -7.8, 53.0, -7.8) == 0.0
        forward = generator._haversine_single(53.0, -7.8, 54.5, -6.1)
        assert forward == pytest.approx(200.8, abs=0.5)
        assert generator._haversine_single(54.5, -6.1, 53.0, -7.8) == pytest.approx(forward)
