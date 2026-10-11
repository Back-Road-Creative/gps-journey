"""Unit tests for the public ``calculate_elevation_gain_m`` helper.

Promotes the sum-of-positive-deltas logic from ``core/processor.py`` to a
module-level public API in ``analysis/route_analyzer.py`` so downstream
consumers (for example per-segment description enrichment) can compute
elevation gain without processing a full Journey.

Mirrors the ``calculate_distance_km`` pattern.
"""

from datetime import datetime, timezone

import pytest

from gps_journey.analysis.route_analyzer import calculate_elevation_gain_m
from gps_journey.core.models import Waypoint


def _wp(elevation, t_minute: int = 0) -> Waypoint:
    return Waypoint(
        latitude=40.0,
        longitude=-75.0,
        timestamp=datetime(2026, 1, 1, 12, t_minute, tzinfo=timezone.utc),
        elevation=elevation,
    )


def test_empty_returns_zero():
    assert calculate_elevation_gain_m([]) == 0.0


def test_single_waypoint_returns_zero():
    assert calculate_elevation_gain_m([_wp(100.0)]) == 0.0


def test_two_waypoints_uphill():
    assert calculate_elevation_gain_m([_wp(100.0, 0), _wp(150.0, 1)]) == pytest.approx(50.0)


def test_two_waypoints_downhill_returns_zero():
    """Loss is not counted — gain only."""
    assert calculate_elevation_gain_m([_wp(150.0, 0), _wp(100.0, 1)]) == 0.0


def test_multi_waypoint_sums_only_positive_deltas():
    # 100 → 150 (+50) → 120 (-30, ignored) → 200 (+80) → 180 (-20, ignored)
    waypoints = [_wp(100.0, 0), _wp(150.0, 1), _wp(120.0, 2), _wp(200.0, 3), _wp(180.0, 4)]
    assert calculate_elevation_gain_m(waypoints) == pytest.approx(130.0)


def test_tuple_input_accepted():
    """Matches the type signature of ``Journey.waypoints`` (tuple)."""
    waypoints = (_wp(100.0, 0), _wp(150.0, 1))
    assert calculate_elevation_gain_m(waypoints) == pytest.approx(50.0)


def test_none_elevation_skipped():
    """Waypoints without elevation data must not break the sum — they are
    silently skipped (matches ``processor.py`` semantics)."""
    waypoints = [_wp(100.0, 0), _wp(None, 1), _wp(200.0, 2)]
    # 100 → None: skip; None → 200: skip. Total = 0 because both edges touch a None.
    assert calculate_elevation_gain_m(waypoints) == 0.0


def test_flat_trajectory_returns_zero():
    waypoints = [_wp(100.0, t) for t in range(5)]
    assert calculate_elevation_gain_m(waypoints) == pytest.approx(0.0, abs=1e-6)
