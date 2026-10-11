"""TDD Tests for RouteAnalyzer - WRITE FIRST, THEN IMPLEMENT."""

from datetime import datetime, timedelta, timezone

import pytest

from gps_journey.analysis.route_analyzer import calculate_distance_km
from gps_journey.core.models import Waypoint


class RoadSeqGeocoder:
    """Road per rounded (lat, lon) key; a missing key returns ``road=None``
    (models a rate-limited / unnamed sample that must not extend a segment)."""

    def __init__(self, roads_by_key):
        self.roads_by_key = roads_by_key

    def reverse_geocode_detailed(self, lat: float, lon: float) -> dict:
        key = (round(lat, 2), round(lon, 2))
        return {
            "village": None,
            "town": None,
            "city": None,
            "county": None,
            "road": self.roads_by_key.get(key),
            "place_class": None,
            "importance": None,
        }


class MockGeocoder:
    """Mock geocoder that returns predictable town/road data."""

    def __init__(self, town_map=None):
        """
        Initialize with town mapping.

        town_map: dict mapping (lat_rounded, lon_rounded) -> town_name
        """
        self.town_map = town_map or {}
        self.road_map = {}

    def reverse_geocode_detailed(self, lat: float, lon: float) -> dict:
        """Return mock geocoding data."""
        key = (round(lat, 2), round(lon, 2))
        town = self.town_map.get(key, "Unknown")
        road = self.road_map.get(key, "N99")

        # Optional per-key metadata for tests that care about class/importance
        meta = getattr(self, "meta_map", {}).get(key, {})

        return {
            "village": town if town != "Unknown" else None,
            "town": None,
            "city": None,
            "county": "County Tarrow",
            "road": road,
            "poi_name": None,
            "place_class": meta.get("place_class"),
            "importance": meta.get("importance"),
            # Optional per-key query-to-match distance (None = unavailable)
            "match_distance_km": getattr(self, "distance_map", {}).get(key),
        }


def create_test_waypoints_multi_town():
    """Create waypoints passing through multiple towns."""
    # Kilvarra (55.2) → Alderford (55.3) → Rosscarra (55.4) → Eastport (55.5)
    waypoints = []
    base_time = datetime(2031, 5, 19, 10, 0, 0, tzinfo=timezone.utc)

    # Kilvarra - 10 waypoints
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.20 + i * 0.001,
                longitude=-7.80,
                timestamp=base_time.replace(minute=i),
                elevation=100.0,
            )
        )

    # Alderford - 10 waypoints
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.30 + i * 0.001,
                longitude=-7.75,
                timestamp=base_time.replace(minute=20 + i),
                elevation=50.0,
            )
        )

    # Rosscarra - 10 waypoints
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.40 + i * 0.001,
                longitude=-7.70,
                timestamp=base_time.replace(minute=40 + i),
                elevation=20.0,
            )
        )

    return tuple(waypoints)


def test_route_analyzer_detects_towns():
    """
    RouteAnalyzer MUST detect towns passed through from sampled waypoints.

    Rewritten so that a town's ``exited`` is stamped at its LAST in-town fix,
    not at the next town's entry. ``sample_interval=2`` gives each town several
    in-town fixes (a real >=3-min span) so detection is validated on genuine
    dwell — not on the old inflated entry->next-entry duration (at interval=10
    each town had a single fix and only survived via that inflation).
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()

    # Mock geocoder that returns different towns
    town_map = {
        (55.20, -7.80): "Kilvarra",
        (55.30, -7.75): "Alderford",
        (55.40, -7.70): "Rosscarra",
    }
    geocoder = MockGeocoder(town_map=town_map)

    # Create analyzer
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)

    # Analyze route
    towns = analyzer.get_towns_passed_through(waypoints)

    # ASSERT: Should detect all 3 towns
    assert len(towns) == 3

    town_names = [t["name"] for t in towns]
    assert "Kilvarra" in town_names
    assert "Alderford" in town_names
    assert "Rosscarra" in town_names


# ---------------------------------------------------------------------------
# A town closes at its LAST in-town fix; townless gaps don't inflate it.
# A road segment closes at its LAST real-road sample; None-samples don't
#     extend it across the gap.
# ---------------------------------------------------------------------------


def _twp(lat, lon, minute, second=0):
    """Timestamped waypoint at 2026-01-01 10:00 + offset (elevation 0)."""
    base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return Waypoint(
        latitude=lat,
        longitude=lon,
        timestamp=base + timedelta(minutes=minute, seconds=second),
        elevation=0.0,
    )


def test_town_duration_is_in_town_span_not_next_town_entry():
    """A town's duration reflects only its real in-town span.

    Trace: town A (3 in-town fixes over 4 min) -> 8 min of no-name rural
    samples -> town B. A's ``exited`` must land at A's LAST in-town fix (4 min),
    NOT at B's entry (15 min). The old machine stamped a town's exit only when
    the next named town appeared, crediting the whole townless gap to A.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = [
        # Town A — 3 in-town fixes spanning minutes 0..4 (real span = 4 min).
        _twp(55.000, -8.000, 0),
        _twp(55.000, -8.000, 2),
        _twp(55.000, -8.000, 4),
        # 8 minutes of no-name rural road (absent from town_map -> None).
        *[_twp(55.10 + 0.01 * k, -8.000, 6 + k) for k in range(8)],
        # Town B — entered at minute 15.
        _twp(55.500, -8.000, 15),
        _twp(55.500, -8.000, 17),
        _twp(55.500, -8.000, 19),
    ]

    geocoder = MockGeocoder(town_map={(55.00, -8.00): "A", (55.50, -8.00): "B"})
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=1)

    towns = analyzer.get_towns_passed_through(tuple(waypoints))
    by_name = {t["name"]: t for t in towns}

    assert "A" in by_name, "town A should survive on its real 4-min dwell"
    assert "B" in by_name
    # A's real in-town span is 4 min (min 0 -> min 4), NOT 15 (min 0 -> B entry).
    assert by_name["A"]["duration_minutes"] == 4


def test_brief_crossroads_before_townless_gap_is_filtered_as_junk():
    """A crossroads clipped for 30 s then a long townless gap is junk.

    Its real in-town span is ~30 s (``duration_minutes`` == 0) so it is
    filtered. Previously, with no later town to close it, its exit was stamped
    at end-of-trace — inflating it to the whole townless tail so it could ship
    as the start/end town.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = [
        # Crossroads clipped for 30 s (two fixes 30 s apart).
        _twp(55.000, -8.000, 0, 0),
        _twp(55.000, -8.000, 0, 30),
        # A long townless gap to the end of the trace (no later named town).
        *[_twp(55.10 + 0.1 * k, -8.000, 2 + 2 * k) for k in range(5)],
    ]

    geocoder = MockGeocoder(town_map={(55.00, -8.00): "Crossroads"})
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=1)

    towns = analyzer.get_towns_passed_through(tuple(waypoints))
    assert all(t["name"] != "Crossroads" for t in towns), (
        "a 30 s crossroads followed by a townless gap must be filtered as junk"
    )


def test_road_segment_distance_excludes_rate_limited_gap():
    """A road segment's distance is only its real span, not the gap.

    Trace: road R1 (short) -> rate-limited/None samples (long) -> road R2.
    R1's distance must cover only the R1 fixes. The old machine kept R1 open
    across the None samples and credited the whole gap to it, inflating the
    >50% dominant-road guard downstream.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    r1 = [_twp(55.000 + 0.001 * k, -8.000, k) for k in range(4)]
    gap = [_twp(55.10 + 0.2 * k, -8.000, 4 + k) for k in range(4)]
    r2 = [_twp(56.000 + 0.001 * k, -8.000, 8 + k) for k in range(3)]
    waypoints = r1 + gap + r2

    geocoder = RoadSeqGeocoder({(55.00, -8.00): "R1", (56.00, -8.00): "R2"})
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=1)

    segments = analyzer.get_road_segments(tuple(waypoints))
    by_road = {s["road"]: s for s in segments}

    assert "R1" in by_road
    r1_real = calculate_distance_km(r1)
    gap_distance = calculate_distance_km(gap)
    # R1's distance is its own ~0.3 km span, NOT R1 + the ~66 km gap.
    assert by_road["R1"]["distance_km"] == pytest.approx(r1_real, rel=1e-6)
    assert by_road["R1"]["distance_km"] < gap_distance


def test_town_passage_has_timing():
    """Each detected town MUST have entry and exit timestamps."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    town_map = {
        (55.20, -7.80): "Kilvarra",
        (55.30, -7.75): "Alderford",
    }
    geocoder = MockGeocoder(town_map=town_map)
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=5)

    towns = analyzer.get_towns_passed_through(waypoints)

    # ASSERT: Every town must have entry/exit times
    for town in towns:
        assert "entered" in town
        assert "exited" in town
        assert town["entered"] is not None
        assert town["exited"] is not None
        assert town["entered"] < town["exited"]


def test_route_analyzer_detects_road_segments():
    """RouteAnalyzer MUST identify road segments traveled."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()

    # Mock different roads for different sections
    geocoder = MockGeocoder()
    geocoder.road_map = {
        (55.20, -7.80): "R901",
        (55.30, -7.75): "R902",
        (55.40, -7.70): "R903",
    }

    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=10)
    segments = analyzer.get_road_segments(waypoints)

    # ASSERT: Should detect road changes
    assert len(segments) >= 2

    road_names = [s["road"] for s in segments]
    assert "R901" in road_names or "R902" in road_names


def test_road_segment_includes_distance():
    """Road segments MUST include distance traveled."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder()

    analyzer = RouteAnalyzer(geocoder=geocoder)
    segments = analyzer.get_road_segments(waypoints)

    # ASSERT: Each segment has distance
    for segment in segments:
        assert "distance_km" in segment
        assert segment["distance_km"] > 0


def test_sampled_waypoints_not_all():
    """RouteAnalyzer MUST sample waypoints, not geocode all."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    # Create many waypoints
    waypoints = create_test_waypoints_multi_town()  # 30 waypoints

    geocoder = MockGeocoder()
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=10)

    # Track API calls
    geocoder.call_count = 0
    original_method = geocoder.reverse_geocode_detailed

    def counting_geocode(lat, lon):
        geocoder.call_count += 1
        return original_method(lat, lon)

    geocoder.reverse_geocode_detailed = counting_geocode

    # Analyze
    analyzer.get_towns_passed_through(waypoints)

    # ASSERT: Should only geocode sampled points
    assert geocoder.call_count <= 5  # 30 waypoints / 10 interval = 3 samples
    assert geocoder.call_count < len(waypoints)  # Definitely not all


# ---------------------------------------------------------------------------
# Phase 1: importance ranking + HOA filter
# ---------------------------------------------------------------------------


def test_town_exposes_place_class_and_importance():
    """Detected towns MUST carry place_class + importance from geocoder.

    Callers (e.g. endpoint selection) rank towns by importance + place_class to
    prefer recognizable cities over tiny villages. Missing values fall back
    to None / 0.0.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder(
        town_map={
            (55.20, -7.80): "Kilvarra",
            (55.30, -7.75): "Alderford",
            (55.40, -7.70): "Rosscarra",
        }
    )
    geocoder.meta_map = {
        (55.20, -7.80): {"place_class": "city", "importance": 0.65},
        (55.30, -7.75): {"place_class": "town", "importance": 0.45},
        (55.40, -7.70): {"place_class": "village", "importance": 0.20},
    }

    # interval=2 gives each town 3 clean in-town fixes (real >=3-min dwell)
    # so it survives on genuine span, not the old entry->next-entry inflation.
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)
    towns = analyzer.get_towns_passed_through(waypoints)

    assert len(towns) >= 2
    for town in towns:
        assert "place_class" in town
        assert "importance" in town

    by_name = {t["name"]: t for t in towns}
    if "Kilvarra" in by_name:
        assert by_name["Kilvarra"]["place_class"] == "city"
        assert by_name["Kilvarra"]["importance"] == pytest.approx(0.65)
    if "Alderford" in by_name:
        assert by_name["Alderford"]["place_class"] == "town"
        assert by_name["Alderford"]["importance"] == pytest.approx(0.45)


def test_town_metadata_defaults_when_missing():
    """When geocoder doesn't return class/importance, towns still have the
    keys with safe defaults (None, 0.0) — caller shouldn't crash.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder(
        town_map={
            (55.20, -7.80): "Kilvarra",
            (55.30, -7.75): "Alderford",
        }
    )
    # No meta_map set — all geocoder results have None for class/importance

    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=5)
    towns = analyzer.get_towns_passed_through(waypoints)

    for town in towns:
        assert town["place_class"] is None
        assert town["importance"] == 0.0


def test_hoa_and_subdivision_names_filtered():
    """HOA / subdivision / mobile home park names MUST be excluded from the
    detected towns list.

    OSM tags arbitrary features as `village`, including unincorporated
    subdivisions like "Quillbrook Subdivision" that leak into generated text as if
    they were real destinations.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    # Build waypoints where middle section passes through a subdivision
    waypoints = []
    base_time = datetime(2031, 3, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Fort Alderwick - 10 waypoints
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.00 + i * 0.001,
                longitude=-7.00,
                timestamp=base_time.replace(minute=i),
                elevation=10.0,
            )
        )
    # "Quillbrook Subdivision" - 10 waypoints (MUST be filtered)
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.05 + i * 0.001,
                longitude=-7.05,
                timestamp=base_time.replace(minute=15 + i),
                elevation=10.0,
            )
        )
    # Beaumere - 10 waypoints
    for i in range(10):
        waypoints.append(
            Waypoint(
                latitude=55.10 + i * 0.001,
                longitude=-7.10,
                timestamp=base_time.replace(minute=30 + i),
                elevation=10.0,
            )
        )

    geocoder = MockGeocoder(
        town_map={
            (55.00, -7.00): "Fort Alderwick",
            (55.05, -7.05): "Quillbrook Subdivision",
            (55.10, -7.10): "Beaumere",
        }
    )

    # interval=2 gives Fort Alderwick / Beaumere 3 clean in-town fixes so
    # they survive on genuine span, not the old entry->next-entry inflation.
    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)
    towns = analyzer.get_towns_passed_through(tuple(waypoints))
    names = [t["name"] for t in towns]

    assert "Quillbrook Subdivision" not in names
    # Real towns still pass through
    assert any(n == "Fort Alderwick" for n in names) or any(n == "Beaumere" for n in names)


def test_all_hoa_patterns_filtered():
    """All documented HOA / community / park suffix patterns are rejected."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    bad_names = [
        "Quillbrook Subdivision",
        "Lakeside Estates",
        "Sun Valley HOA",
        "Pine Community",
        "River Mobile Home",
        "Oak Trailer Park",
        "Elm Apartments",
    ]

    base_time = datetime(2031, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    waypoints = []
    for i in range(20):
        waypoints.append(
            Waypoint(
                latitude=40.00 + i * 0.001,
                longitude=-75.00,
                timestamp=base_time.replace(minute=i * 2),
                elevation=10.0,
            )
        )

    for bad in bad_names:
        geocoder = MockGeocoder(town_map={(40.00, -75.00): bad})
        analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)
        towns = analyzer.get_towns_passed_through(tuple(waypoints))
        assert all(t["name"] != bad for t in towns), f"{bad!r} was not filtered"


def test_far_match_town_votes_filtered_and_closest_distance_kept():
    """A sample whose OSM match is >MAX_SETTLEMENT_MATCH_KM from the waypoint
    is a far-away catchment feature — its town must not vote. Surviving towns
    carry their closest match distance for downstream ranking."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder(
        town_map={
            (55.20, -7.80): "Kilvarra",
            (55.30, -7.75): "CatchmentVillage",
            (55.40, -7.70): "Rosscarra",
        }
    )
    geocoder.distance_map = {
        (55.20, -7.80): 0.8,
        (55.30, -7.75): 8.0,  # matched object 8 km away — rural catchment
        (55.40, -7.70): 0.5,
    }

    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)
    towns = analyzer.get_towns_passed_through(waypoints)
    by_name = {t["name"]: t for t in towns}

    assert "CatchmentVillage" not in by_name, "far-match town must not vote"
    assert by_name["Kilvarra"]["match_distance_km"] == pytest.approx(0.8)
    assert by_name["Rosscarra"]["match_distance_km"] == pytest.approx(0.5)


def test_town_match_distance_defaults_to_none_when_unavailable():
    """Geocoders that don't report match distance (legacy cache dicts) keep
    today's behavior: towns vote normally and carry match_distance_km=None."""
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder(town_map={(55.20, -7.80): "Kilvarra"})

    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=2)
    towns = analyzer.get_towns_passed_through(waypoints)

    assert any(t["name"] == "Kilvarra" for t in towns)
    for town in towns:
        assert town["match_distance_km"] is None


def test_towns_preserve_chronological_order():
    """get_towns_passed_through MUST return towns in chronological order.

    Importance-based ranking is the caller's responsibility — the analyzer
    just supplies the data.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    waypoints = create_test_waypoints_multi_town()
    geocoder = MockGeocoder(
        town_map={
            (55.20, -7.80): "Kilvarra",
            (55.30, -7.75): "Alderford",
            (55.40, -7.70): "Rosscarra",
        }
    )
    # High importance for the LATE town — still appears last
    geocoder.meta_map = {
        (55.20, -7.80): {"place_class": "village", "importance": 0.10},
        (55.30, -7.75): {"place_class": "village", "importance": 0.20},
        (55.40, -7.70): {"place_class": "city", "importance": 0.95},
    }

    analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=5)
    towns = analyzer.get_towns_passed_through(waypoints)

    # Result must be chronological — Kilvarra first, Rosscarra last
    names = [t["name"] for t in towns]
    if "Kilvarra" in names and "Rosscarra" in names:
        assert names.index("Kilvarra") < names.index("Rosscarra")
