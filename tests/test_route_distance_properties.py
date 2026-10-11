"""Property-based tests: the Haversine distance math holds its geometry.

``_haversine_km`` is a great-circle metric on the sphere, so it must be
symmetric, zero on the diagonal, non-negative, bounded by half the Earth's
circumference, and obey the triangle inequality. ``calculate_distance_km``
sums it along a trajectory, so the sum must not care which way the
trajectory is walked. Hypothesis draws the coordinates; every test here is
collected by ``pytest -k property``.
"""

from datetime import datetime, timezone
from math import pi

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gps_journey.analysis.route_analyzer import (
    _EARTH_RADIUS_KM,
    RouteAnalyzer,
    _haversine_km,
    calculate_distance_km,
)
from gps_journey.core.models import Waypoint

# Half the Earth's circumference: no two points on a sphere are further
# apart than antipodes.
_MAX_GREAT_CIRCLE_KM = pi * _EARTH_RADIUS_KM

# Float tolerance for equalities that only hold up to rounding. 1e-6 km is
# one millimetre; the arithmetic differs by far less than that.
_TOL_KM = 1e-6

_lat = st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False)
_lon = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)
_point = st.tuples(_lat, _lon)

_settings = settings(deadline=None, max_examples=200)


def _wp(point: tuple[float, float]) -> Waypoint:
    return Waypoint(
        latitude=point[0],
        longitude=point[1],
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )


@_settings
@given(a=_point, b=_point)
def test_property_symmetric(a, b):
    assert _haversine_km(*a, *b) == pytest.approx(_haversine_km(*b, *a), abs=_TOL_KM)


@_settings
@given(a=_point)
def test_property_identity_is_zero(a):
    assert _haversine_km(*a, *a) == 0.0


@_settings
@given(a=_point, b=_point)
def test_property_non_negative(a, b):
    assert _haversine_km(*a, *b) >= 0.0


@_settings
@given(a=_point, b=_point)
def test_property_bounded_by_half_circumference(a, b):
    assert _haversine_km(*a, *b) <= _MAX_GREAT_CIRCLE_KM + _TOL_KM


@_settings
@given(a=_point, b=_point, c=_point)
def test_property_triangle_inequality(a, b, c):
    direct = _haversine_km(*a, *c)
    via_b = _haversine_km(*a, *b) + _haversine_km(*b, *c)
    assert direct <= via_b + _TOL_KM


@_settings
@given(a=_point, b=_point)
def test_property_method_form_matches_module_function(a, b):
    """``RouteAnalyzer._haversine`` delegates; pin that it stays the same metric."""
    analyzer = RouteAnalyzer()
    assert analyzer._haversine(*a, *b) == _haversine_km(*a, *b)


@_settings
@given(points=st.lists(_point, min_size=2, max_size=12))
def test_property_reversed_trajectory_sums_the_same(points):
    forward = [_wp(p) for p in points]
    backward = list(reversed(forward))
    assert calculate_distance_km(backward) == pytest.approx(
        calculate_distance_km(forward), abs=_TOL_KM
    )


@_settings
@given(points=st.lists(_point, min_size=2, max_size=12))
def test_property_trajectory_sum_is_at_least_endpoint_distance(points):
    """Walking every leg is never shorter than the straight great-circle hop."""
    total = calculate_distance_km([_wp(p) for p in points])
    endpoints = _haversine_km(*points[0], *points[-1])
    assert total + _TOL_KM >= endpoints
