"""Unit tests for the public ``calculate_distance_km`` helper.

Promotes ``RouteAnalyzer._calculate_distance`` to a module-level public
API so downstream consumers (for example per-segment description
enrichment) can compute total Haversine distance without
instantiating a ``RouteAnalyzer``.
"""

from datetime import datetime, timezone

import pytest

from gps_journey.analysis.route_analyzer import calculate_distance_km
from gps_journey.core.models import Waypoint


def _wp(lat: float, lon: float, t_minute: int = 0) -> Waypoint:
    return Waypoint(
        latitude=lat,
        longitude=lon,
        timestamp=datetime(2026, 1, 1, 12, t_minute, tzinfo=timezone.utc),
        elevation=0.0,
    )


def test_empty_returns_zero():
    assert calculate_distance_km([]) == 0.0


def test_single_waypoint_returns_zero():
    assert calculate_distance_km([_wp(40.0, -75.0)]) == 0.0


def test_two_waypoints_haversine():
    # Roughly one degree latitude ~111 km
    result = calculate_distance_km([_wp(40.0, -75.0), _wp(41.0, -75.0)])
    assert 110.0 < result < 112.0


def test_multi_waypoint_sums_segments():
    # 40,-75 → 41,-75 (~111 km) → 41,-74 (~84 km at that latitude) ≈ 195 km
    waypoints = [_wp(40.0, -75.0, 0), _wp(41.0, -75.0, 1), _wp(41.0, -74.0, 2)]
    result = calculate_distance_km(waypoints)
    assert 190.0 < result < 200.0


def test_tuple_input_accepted():
    """Matches the type signature of ``Journey.waypoints`` (tuple)."""
    waypoints = (_wp(40.0, -75.0), _wp(41.0, -75.0))
    result = calculate_distance_km(waypoints)
    assert 110.0 < result < 112.0


def test_zero_distance_when_all_waypoints_collocated():
    waypoints = [_wp(40.0, -75.0, t) for t in range(5)]
    assert calculate_distance_km(waypoints) == pytest.approx(0.0, abs=1e-6)


def test_route_analyzer_private_method_uses_public_helper():
    """RouteAnalyzer._calculate_distance must delegate to the public helper.

    Prevents the four-way Haversine duplication that existed before this PR
    from re-emerging. If a future refactor inlines the math back into
    ``_calculate_distance``, this test fails.
    """
    from gps_journey.analysis.route_analyzer import RouteAnalyzer

    analyzer = RouteAnalyzer()
    waypoints = [_wp(40.0, -75.0), _wp(41.0, -75.0)]
    private = analyzer._calculate_distance(waypoints)
    public = calculate_distance_km(waypoints)
    assert private == pytest.approx(public, abs=1e-9)
