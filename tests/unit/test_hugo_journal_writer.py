"""Characterization tests for gps_journey.hugo.journal_writer.

These pin what JournalWriter produces today (journal text, stop detection, which
stops are worth mentioning, distance maths) so a pure restyle of the module can be
shown to change nothing. The geocoder is a fake that returns canned answers; there is
no network and no clock.
"""

import logging
from datetime import datetime, timedelta

import pytest

from gps_journey.core.models import Journey, JourneyStatistics, Location, Waypoint
from gps_journey.hugo.journal_writer import JournalWriter

BASE = datetime(2026, 6, 1, 9, 0)


class FakeGeocoder:
    """Canned reverse-geocode answers keyed by latitude; an Exception value is raised."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def reverse_geocode_detailed(self, lat, lon):
        self.calls.append((lat, lon))
        result = self.results.get(lat, {})
        if isinstance(result, Exception):
            raise result
        return result


def _stats(distance_km):
    return JourneyStatistics(
        total_distance_km=distance_km,
        total_distance_miles=distance_km * 0.621371,
        total_elevation_gain_m=0.0,
        total_elevation_loss_m=0.0,
        moving_time_seconds=0,
        stopped_time_seconds=0,
        average_speed_kmh=0.0,
        max_speed_kmh=0.0,
        min_elevation_m=0.0,
        max_elevation_m=0.0,
    )


def _wp(lat, lon, when, location=None):
    return Waypoint(latitude=lat, longitude=lon, timestamp=when, location=location)


def _track(*points):
    """Waypoints from (lat, lon, minutes after 09:00 UTC) tuples."""
    return [_wp(lat, lon, BASE + timedelta(minutes=minutes)) for lat, lon, minutes in points]


def _stop(lat=53.0, lon=-7.8, duration=30):
    return {"time": BASE, "duration": duration, "lat": lat, "lon": lon}


class TestInit:
    def test_geocoder_defaults_to_none(self):
        assert JournalWriter().geocoder is None

    def test_geocoder_is_stored(self):
        geocoder = FakeGeocoder({})
        assert JournalWriter(geocoder).geocoder is geocoder


class TestGenerate:
    def test_metric_journal_with_a_poi_stop_and_a_stop_free_day(self):
        ennerby = Location(
            latitude=53.0, longitude=-7.8, name="Ennerby", city="Ennerby", country="Ireland"
        )
        gortmore = Location(latitude=53.2, longitude=-7.8, city="Gortmore", country="Ireland")
        journey = Journey(
            start_date=datetime(2026, 6, 1, 9, 0),
            end_date=datetime(2026, 6, 3, 9, 0),
            waypoints=(
                _wp(53.0, -7.8, datetime(2026, 6, 1, 9, 0), ennerby),
                _wp(53.0, -7.8, datetime(2026, 6, 1, 9, 30)),
                _wp(53.2, -7.8, datetime(2026, 6, 1, 10, 0), gortmore),
                _wp(53.2, -7.8, datetime(2026, 6, 2, 6, 0)),
                _wp(53.3, -7.8, datetime(2026, 6, 2, 6, 45)),
                _wp(53.5, -7.8, datetime(2026, 6, 2, 8, 30)),
            ),
            statistics=_stats(1234.4),
        )
        geocoder = FakeGeocoder({53.0: {"poi_name": "Hartigan's Pub", "road": "N98"}})

        text = JournalWriter(geocoder).generate(journey)

        assert text.split("\n") == [
            "# Ireland Road Trip - June 2026",
            "",
            "A 2-day journey covering 1,234 km through Ireland.",
            "",
            "---",
            "",
            "## Monday, June 01",
            "",
            (
                "We left Ennerby at 08:00 AM. At 08:00 AM we stopped at Hartigan's Pub for 30 minutes, "
                "arriving in Gortmore at 09:00 AM."
            ),
            "",
            "Distance: 22 km | Duration: 1.0 hours",
            "",
            "## Tuesday, June 02",
            "",
            "We left at 05:00 AM, arriving at 07:30 AM.",
            "",
            "Distance: 33 km | Duration: 2.5 hours",
            "",
        ]
        assert geocoder.calls == [(53.0, -7.8)]

    def test_us_journey_reads_in_miles_with_a_given_title_and_a_town_stop(self):
        montana = Location(
            latitude=47.0, longitude=-110.0, state="Montana", country="United States"
        )
        havre = Location(latitude=48.0, longitude=-110.0, city="Havre", country="United States")
        journey = Journey(
            start_date=datetime(2026, 7, 4, 15, 0),
            end_date=datetime(2026, 7, 7, 15, 0),
            waypoints=(
                _wp(47.0, -110.0, datetime(2026, 7, 4, 15, 0)),
                _wp(47.0, -110.0, datetime(2026, 7, 4, 15, 45)),
                _wp(48.0, -110.0, datetime(2026, 7, 4, 17, 0), havre),
            ),
            statistics=_stats(500.0),
            start_location=montana,
            title="Big Sky Loop",
        )
        geocoder = FakeGeocoder({47.0: {"town": "Lewistown"}})

        text = JournalWriter(geocoder).generate(journey)

        assert text.split("\n") == [
            "# Big Sky Loop",
            "",
            "A 3-day journey covering 311 mi through Montana.",
            "",
            "---",
            "",
            "## Saturday, July 04",
            "",
            (
                "We left at 08:00 AM. At 08:00 AM we stopped at Lewistown for 45 minutes, "
                "arriving in Havre at 10:00 AM."
            ),
            "",
            "Distance: 69 mi | Duration: 2.0 hours",
            "",
        ]

    def test_journey_with_no_waypoints_has_only_the_header(self):
        journey = Journey(
            start_date=datetime(2026, 6, 1, 9, 0),
            end_date=datetime(2026, 6, 3, 9, 0),
            statistics=_stats(100.0),
        )
        text = JournalWriter().generate(journey)
        assert text == "# Road Trip - June 2026\n\nA 2-day journey covering 100 km.\n\n---\n"

    def test_unlocated_journey_without_a_geocoder_drops_its_stops(self):
        journey = Journey(
            start_date=datetime(2026, 6, 1, 9, 0),
            end_date=datetime(2026, 6, 2, 9, 0),
            waypoints=(
                _wp(10.0, 0.0, datetime(2026, 6, 1, 9, 0)),
                _wp(10.0, 0.0, datetime(2026, 6, 1, 9, 10)),
            ),
            statistics=_stats(12.0),
        )
        text = JournalWriter().generate(journey)
        assert text.split("\n") == [
            "# Road Trip - June 2026",
            "",
            "A 1-day journey covering 12 km.",
            "",
            "---",
            "",
            "## Monday, June 01",
            "",
            "We left at 09:00 AM, arriving at 09:10 AM.",
            "",
            "Distance: 0 km | Duration: 0.2 hours",
            "",
        ]


class TestGroupByDay:
    def test_days_follow_longitude_local_time_not_utc(self):
        waypoints = (
            _wp(45.0, -100.0, datetime(2026, 6, 1, 20, 0)),
            _wp(45.0, -100.0, datetime(2026, 6, 2, 3, 0)),
            _wp(45.0, -100.0, datetime(2026, 6, 2, 8, 0)),
        )
        by_day = JournalWriter()._group_by_day(waypoints)
        assert {day.isoformat(): len(group) for day, group in by_day.items()} == {
            "2026-06-01": 2,
            "2026-06-02": 1,
        }


class TestGetSpecificLocation:
    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            (None, None),
            (
                Location(latitude=1.0, longitude=2.0, name="Harbourview", city="Kilvarra"),
                "Harbourview",
            ),
            (
                Location(latitude=1.0, longitude=2.0, city="Kilvarra", county="Tarrow"),
                "Kilvarra",
            ),
            (Location(latitude=1.0, longitude=2.0, county="Tarrow"), None),
        ],
    )
    def test_prefers_name_then_city_and_skips_county_only(self, location, expected):
        assert JournalWriter()._get_specific_location(location) == expected


class TestDetectStops:
    def test_stationary_run_becomes_one_stop(self):
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 5), (53.0, -7.8, 10), (53.5, -7.8, 20))
        stops = JournalWriter()._detect_stops(track)
        assert len(stops) == 1
        assert stops[0] == {
            "time": BASE,
            "duration": 10,
            "lat": 53.0,
            "lon": -7.8,
            "waypoint": track[0],
        }

    def test_shorter_than_five_minutes_is_not_a_stop(self):
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 4), (53.5, -7.8, 10))
        assert JournalWriter()._detect_stops(track) == []

    def test_exactly_five_minutes_is_a_stop(self):
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 5), (53.5, -7.8, 10))
        assert [s["duration"] for s in JournalWriter()._detect_stops(track)] == [5]

    def test_minimum_duration_is_adjustable(self):
        track = _track((53.0, -7.8, 0), (53.0, -7.8, 2), (53.5, -7.8, 10))
        writer = JournalWriter()
        assert writer._detect_stops(track) == []
        assert [s["duration"] for s in writer._detect_stops(track, min_duration_min=1)] == [2]

    def test_moving_track_has_no_stops(self):
        track = _track((53.0, -7.8, 0), (53.1, -7.8, 5), (53.2, -7.8, 10))
        assert JournalWriter()._detect_stops(track) == []

    def test_fifty_metre_threshold(self):
        writer = JournalWriter()
        near = _track((53.0, -7.8, 0), (53.0003, -7.8, 6), (53.5, -7.8, 20))  # about 33 m
        far = _track((53.0, -7.8, 0), (53.001, -7.8, 6), (53.5, -7.8, 20))  # about 111 m
        assert [s["duration"] for s in writer._detect_stops(near)] == [6]
        assert writer._detect_stops(far) == []

    def test_two_separate_stops(self):
        track = _track(
            (53.0, -7.8, 0),
            (53.0, -7.8, 10),
            (53.5, -7.8, 30),
            (54.0, -7.8, 40),
            (54.0, -7.8, 47),
            (55.0, -7.8, 60),
        )
        stops = JournalWriter()._detect_stops(track)
        assert [(s["lat"], s["duration"]) for s in stops] == [(53.0, 10), (54.0, 7)]


class TestFilterMeaningfulStops:
    def test_without_a_geocoder_nothing_is_meaningful(self):
        assert JournalWriter()._filter_meaningful_stops([_stop()]) == []

    def test_named_poi_wins_over_everything(self):
        geo = {"poi_name": "Hartigan's Pub", "village": "Kilmorran", "road": "N98"}
        geocoder = FakeGeocoder({53.0: geo})
        stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop()])
        assert len(stops) == 1
        assert stops[0]["type"] == "poi"
        assert stops[0]["meaningful_name"] == "Hartigan's Pub"
        assert stops[0]["geo"] == geo
        assert geocoder.calls == [(53.0, -7.8)]

    def test_village_is_preferred_over_town_after_ten_minutes(self):
        geocoder = FakeGeocoder({53.0: {"village": "Kilmorran", "town": "Ennisbeg"}})
        stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop(duration=10)])
        assert [(s["type"], s["meaningful_name"]) for s in stops] == [("town", "Kilmorran")]

    def test_town_alone_counts_after_ten_minutes(self):
        geocoder = FakeGeocoder({53.0: {"town": "Ennisbeg"}})
        stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop(duration=10)])
        assert [(s["type"], s["meaningful_name"]) for s in stops] == [("town", "Ennisbeg")]

    def test_short_town_stop_is_dropped_even_with_a_major_road(self, caplog):
        geocoder = FakeGeocoder({53.0: {"village": "Kilmorran", "road": "N98"}})
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.journal_writer"):
            stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop(duration=9)])
        assert stops == []
        assert caplog.records == []

    def test_long_stop_on_a_major_road_is_a_route_stop(self):
        geocoder = FakeGeocoder({53.0: {"road": "R904"}})
        stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop(duration=15)])
        assert [(s["type"], s["meaningful_name"]) for s in stops] == [("route", "R904")]

    @pytest.mark.parametrize(
        ("geo", "duration"),
        [({"road": "N98"}, 14), ({"road": "L1234"}, 60), ({}, 30)],
    )
    def test_everything_else_is_skipped_with_a_debug_note(self, geo, duration, caplog):
        geocoder = FakeGeocoder({53.0: geo})
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.journal_writer"):
            stops = JournalWriter(geocoder)._filter_meaningful_stops([_stop(duration=duration)])
        assert stops == []
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (logging.DEBUG, "Skipping stop at 53.0000, -7.8000 - no POI")
        ]

    def test_geocoder_failure_skips_only_that_stop(self, caplog):
        geocoder = FakeGeocoder({53.0: RuntimeError("boom"), 54.0: {"poi_name": "Cliffs Cafe"}})
        stops_in = [_stop(lat=53.0), _stop(lat=54.0)]
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.journal_writer"):
            stops = JournalWriter(geocoder)._filter_meaningful_stops(stops_in)
        assert [s["meaningful_name"] for s in stops] == ["Cliffs Cafe"]
        assert geocoder.calls == [(53.0, -7.8), (54.0, -7.8)]
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (logging.DEBUG, "Failed to geocode stop: boom")
        ]


class TestDistance:
    def test_calculate_distance_needs_two_points(self):
        writer = JournalWriter()
        assert writer._calculate_distance([]) == 0.0
        assert writer._calculate_distance(_track((53.0, -7.8, 0))) == 0.0

    def test_calculate_distance_sums_the_legs(self):
        track = _track((0.0, 0.0, 0), (0.0, 1.0, 5), (1.0, 1.0, 10))
        assert JournalWriter()._calculate_distance(track) == pytest.approx(222.3898, abs=1e-3)

    def test_haversine_one_degree_of_longitude_on_the_equator(self):
        assert JournalWriter()._haversine(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.1949, abs=1e-3)

    def test_haversine_shrinks_with_latitude(self):
        assert JournalWriter()._haversine(60.0, 0.0, 60.0, 1.0) == pytest.approx(55.5975, abs=1e-2)

    def test_haversine_same_point_is_zero_and_the_result_is_symmetric(self):
        writer = JournalWriter()
        assert writer._haversine(53.0, -7.8, 53.0, -7.8) == 0.0
        forward = writer._haversine(53.0, -7.8, 54.5, -6.1)
        assert forward == pytest.approx(200.8, abs=0.5)
        assert writer._haversine(54.5, -6.1, 53.0, -7.8) == pytest.approx(forward)
