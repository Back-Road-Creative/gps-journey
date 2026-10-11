"""Unit tests for ``RouteAnalyzer.get_regions_passed_through``.

Powers a long-form "Through:" description line in downstream consumers.
"""

from datetime import datetime, timezone

from gps_journey.analysis.route_analyzer import RouteAnalyzer, _region_admin_level
from gps_journey.core.models import Waypoint


def _wp(lat: float, lon: float, t_minute: int = 0) -> Waypoint:
    return Waypoint(
        latitude=lat,
        longitude=lon,
        timestamp=datetime(2026, 1, 1, 12, t_minute, tzinfo=timezone.utc),
        elevation=0.0,
    )


class _FakeGeocoder:
    """Returns a queued geo dict per call (one per sampled waypoint)."""

    def __init__(self, results: list[dict]):
        self._results = list(results)
        self.calls: list[tuple[float, float]] = []

    def reverse_geocode_detailed(self, lat: float, lon: float) -> dict:
        self.calls.append((lat, lon))
        if not self._results:
            return {}
        return self._results.pop(0)


def _geo(county: str | None = None, state: str | None = None, country: str | None = None) -> dict:
    return {"county": county, "state": state, "country": country}


# ────────────────────────────────────────────────────────────────────
# _region_admin_level
# ────────────────────────────────────────────────────────────────────


def test_admin_level_ireland_is_county():
    assert _region_admin_level("Ireland") == "county"


def test_admin_level_usa_aliases_are_state():
    for alias in ("USA", "usa", "United States", "U.S.", "United States of America"):
        assert _region_admin_level(alias) == "state"


def test_admin_level_default_county_for_unknown():
    assert _region_admin_level("France") == "county"
    assert _region_admin_level(None) == "county"
    assert _region_admin_level("") == "county"


# ────────────────────────────────────────────────────────────────────
# get_regions_passed_through — Ireland (county + prefix)
# ────────────────────────────────────────────────────────────────────


def test_ireland_county_prefix_added_when_missing():
    geocoder = _FakeGeocoder([_geo(county="Kerry"), _geo(county="Cork")])
    # 2 waypoints → step = max(1, 2//20) = 1 → both sampled.
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, 0), _wp(51.9, -8.5, 1)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry", "County Cork"]
    assert all(r["admin_level"] == "county" for r in out)
    assert all(r["country"] == "Ireland" for r in out)


def test_ireland_county_prefix_preserved_when_present():
    geocoder = _FakeGeocoder([_geo(county="County Kerry")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through([_wp(52.0, -9.5)], country="Ireland")
    assert out[0]["name"] == "County Kerry"  # NOT "County County Kerry"


# ────────────────────────────────────────────────────────────────────
# get_regions_passed_through — USA (state field, no prefix)
# ────────────────────────────────────────────────────────────────────


def test_usa_uses_state_not_county():
    geocoder = _FakeGeocoder(
        [
            _geo(county="Kerr County", state="Texas"),
            _geo(county="Bexar County", state="Texas"),
        ]
    )
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(30.0, -99.0, 0), _wp(29.5, -98.5, 1)],
        country="USA",
    )
    assert [r["name"] for r in out] == ["Texas"]  # adjacent dedup collapses identical states
    assert out[0]["admin_level"] == "state"


def test_usa_state_crossing_emits_two_entries():
    geocoder = _FakeGeocoder([_geo(state="Texas"), _geo(state="New Mexico")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(31.7, -106.5, 0), _wp(32.3, -106.8, 1)],
        country="USA",
    )
    assert [r["name"] for r in out] == ["Texas", "New Mexico"]


# ────────────────────────────────────────────────────────────────────
# Other countries (county verbatim)
# ────────────────────────────────────────────────────────────────────


def test_other_country_uses_county_verbatim_no_prefix():
    geocoder = _FakeGeocoder([_geo(county="Cornwall")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through([_wp(50.0, -5.0)], country="United Kingdom")
    assert out[0]["name"] == "Cornwall"
    assert out[0]["admin_level"] == "county"


def test_no_country_defaults_to_county_no_prefix():
    geocoder = _FakeGeocoder([_geo(county="Kerry")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through([_wp(52.0, -9.5)], country=None)
    assert out[0]["name"] == "Kerry"  # No prefix — only Ireland gets normalised


# ────────────────────────────────────────────────────────────────────
# Dedup + chronological order
# ────────────────────────────────────────────────────────────────────


def test_adjacent_dedup_collapses_repeats():
    geocoder = _FakeGeocoder(
        [_geo(county="Kerry"), _geo(county="Kerry"), _geo(county="Cork"), _geo(county="Cork")]
    )
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, i) for i in range(4)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry", "County Cork"]


def test_non_adjacent_repeat_is_kept():
    """Re-entering a county counts again (chronological order preserved)."""
    geocoder = _FakeGeocoder([_geo(county="Kerry"), _geo(county="Cork"), _geo(county="Kerry")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, i) for i in range(3)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry", "County Cork", "County Kerry"]


# ────────────────────────────────────────────────────────────────────
# HOA filter (defensive — should be rare at county/state level)
# ────────────────────────────────────────────────────────────────────


def test_hoa_name_filtered():
    geocoder = _FakeGeocoder([_geo(county="Sunset Estates"), _geo(county="Kerry")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, 0), _wp(52.1, -9.4, 1)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry"]


# ────────────────────────────────────────────────────────────────────
# Edge cases
# ────────────────────────────────────────────────────────────────────


def test_empty_waypoints_returns_empty():
    analyzer = RouteAnalyzer(geocoder=_FakeGeocoder([]))
    assert analyzer.get_regions_passed_through([], country="Ireland") == []


def test_no_geocoder_returns_empty():
    analyzer = RouteAnalyzer(geocoder=None)
    assert analyzer.get_regions_passed_through([_wp(52.0, -9.5)], country="Ireland") == []


def test_missing_admin_field_skipped():
    """A geocode result with no county / state contributes nothing."""
    geocoder = _FakeGeocoder([_geo(county=None), _geo(county="Kerry")])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, 0), _wp(52.1, -9.4, 1)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry"]


def test_geocoder_exception_is_swallowed():
    """A single bad reverse_geocode_detailed call must not abort the scan."""

    class _Flaky:
        def __init__(self):
            self._n = 0

        def reverse_geocode_detailed(self, lat: float, lon: float) -> dict:
            self._n += 1
            if self._n == 1:
                raise RuntimeError("boom")
            return _geo(county="Kerry")

    analyzer = RouteAnalyzer(geocoder=_Flaky())
    out = analyzer.get_regions_passed_through(
        [_wp(52.0, -9.5, 0), _wp(52.1, -9.4, 1)],
        country="Ireland",
    )
    assert [r["name"] for r in out] == ["County Kerry"]


def test_sparse_sampling_caps_calls_at_about_twenty():
    """Sparse sampling: step = max(1, len // 20) caps calls to ≤ ~21."""
    geocoder = _FakeGeocoder([_geo(county="Kerry") for _ in range(50)])
    analyzer = RouteAnalyzer(geocoder=geocoder)
    waypoints = [_wp(52.0 + i * 0.001, -9.5, i % 60) for i in range(500)]
    analyzer.get_regions_passed_through(waypoints, country="Ireland")
    # step = 500 // 20 = 25 → 500 / 25 = 20 sampled points.
    assert len(geocoder.calls) == 20
