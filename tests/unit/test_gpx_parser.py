"""Unit tests for GPX parser."""

from datetime import datetime
from pathlib import Path

import pytest

from gps_journey.core.gpx_parser import GPXParser
from gps_journey.core.models import Journey


@pytest.fixture
def sample_gpx_content() -> str:
    """Sample GPX file content."""
    return """<?xml version="1.0"?>
<gpx version="1.1" creator="GPS Journey Test">
  <metadata>
    <name>Test Journey</name>
  </metadata>
  <trk>
    <name>Test Track</name>
    <trkseg>
      <trkpt lat="40.000" lon="-100.000">
        <ele>100</ele>
        <time>2030-06-01T10:00:00Z</time>
      </trkpt>
      <trkpt lat="40.100" lon="-100.100">
        <ele>150</ele>
        <time>2030-06-01T11:00:00Z</time>
      </trkpt>
      <trkpt lat="40.200" lon="-100.200">
        <ele>120</ele>
        <time>2030-06-01T12:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""


@pytest.fixture
def sample_gpx_file(tmp_path: Path, sample_gpx_content: str) -> Path:
    """Create a temporary GPX file."""
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(sample_gpx_content)
    return gpx_file


def test_parse_valid_gpx(sample_gpx_file: Path):
    """Test parsing a valid GPX file."""
    parser = GPXParser()
    journey = parser.parse(sample_gpx_file)

    assert isinstance(journey, Journey)
    assert len(journey.waypoints) == 3
    assert journey.duration_days == 0  # Same day
    assert journey.start_date < journey.end_date


def test_parse_nonexistent_file():
    """Test parsing a nonexistent file raises FileNotFoundError."""
    parser = GPXParser()
    with pytest.raises(FileNotFoundError):
        parser.parse("nonexistent.gpx")


def test_waypoint_extraction(sample_gpx_file: Path):
    """Test waypoint extraction from GPX."""
    parser = GPXParser()
    journey = parser.parse(sample_gpx_file)

    # Check first waypoint
    first = journey.waypoints[0]
    assert first.latitude == 40.0
    assert first.longitude == -100.0
    assert first.elevation == 100

    # Check last waypoint
    last = journey.waypoints[-1]
    assert last.latitude == 40.2
    assert last.longitude == -100.2


def test_statistics_calculation(sample_gpx_file: Path):
    """Test journey statistics calculation."""
    parser = GPXParser()
    journey = parser.parse(sample_gpx_file)

    assert journey.statistics is not None
    assert journey.statistics.total_distance_km > 0
    assert journey.statistics.total_elevation_gain_m >= 0


def test_empty_gpx_file(tmp_path: Path):
    """Test parsing an empty GPX file raises ValueError."""
    empty_gpx = tmp_path / "empty.gpx"
    empty_gpx.write_text("""<?xml version="1.0"?>
<gpx version="1.1" creator="Test">
</gpx>
""")

    parser = GPXParser()
    with pytest.raises(ValueError, match="no tracks"):
        parser.parse(empty_gpx)


def test_malformed_gpx_file(tmp_path: Path):
    """Test parsing a malformed GPX file raises ValueError."""
    malformed_gpx = tmp_path / "malformed.gpx"
    malformed_gpx.write_text("not valid XML")

    parser = GPXParser()
    with pytest.raises(ValueError, match="Failed to parse"):
        parser.parse(malformed_gpx)


# --- trackpoints-only by default + no naive datetime.now() fallback ---


@pytest.fixture
def gpx_with_far_wpt(tmp_path: Path) -> Path:
    """External GPX: a timed track plus a saved-favorite <wpt> far away."""
    content = """<?xml version="1.0"?>
<gpx version="1.1" creator="External GPS">
  <wpt lat="60.000" lon="-10.000">
    <name>Home (saved favorite)</name>
    <time>2020-01-01T00:00:00Z</time>
  </wpt>
  <trk>
    <trkseg>
      <trkpt lat="40.000" lon="-100.000">
        <time>2030-06-01T10:00:00Z</time>
      </trkpt>
      <trkpt lat="40.100" lon="-100.100">
        <time>2030-06-01T11:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    gpx_file = tmp_path / "external.gpx"
    gpx_file.write_text(content)
    return gpx_file


@pytest.fixture
def gpx_with_timeless_markers(tmp_path: Path) -> Path:
    """Timed track plus a <wpt> and a <rtept> that carry NO <time>."""
    content = """<?xml version="1.0"?>
<gpx version="1.1" creator="External GPS">
  <wpt lat="60.000" lon="-10.000">
    <name>Timeless favorite</name>
  </wpt>
  <rte>
    <name>Saved route</name>
    <rtept lat="61.000" lon="-11.000"></rtept>
  </rte>
  <trk>
    <trkseg>
      <trkpt lat="40.000" lon="-100.000">
        <time>2030-06-01T10:00:00Z</time>
      </trkpt>
      <trkpt lat="40.100" lon="-100.100">
        <time>2030-06-01T11:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    gpx_file = tmp_path / "timeless.gpx"
    gpx_file.write_text(content)
    return gpx_file


def test_far_wpt_excluded_from_trace_by_default(gpx_with_far_wpt: Path):
    """(a) A saved-favorite <wpt> far from the track must NOT pollute the trace."""
    journey = GPXParser().parse(gpx_with_far_wpt)

    # Only the two track points survive; the far-away waypoint is dropped.
    assert len(journey.waypoints) == 2
    coords = {(w.latitude, w.longitude) for w in journey.waypoints}
    assert (60.0, -10.0) not in coords
    assert coords == {(40.0, -100.0), (40.1, -100.1)}


def test_timeless_markers_dropped_no_now_fallback(gpx_with_timeless_markers: Path):
    """(b) Timeless <wpt>/<rtept> are dropped, never stamped with datetime.now().

    Even with the opt-in enabled, a marker without a tz-aware <time> must be
    dropped rather than given a naive now() — which would both fabricate the
    journey bounds and raise TypeError when sorted against tz-aware trackpoints.
    """
    # Opt-in path exercises the wpt/route loops; timeless markers still dropped.
    journey = GPXParser(include_waypoints=True).parse(gpx_with_timeless_markers)

    assert len(journey.waypoints) == 2
    coords = {(w.latitude, w.longitude) for w in journey.waypoints}
    assert (60.0, -10.0) not in coords  # timeless <wpt>
    assert (61.0, -11.0) not in coords  # timeless <rtept>
    # Journey bounds derive from real trackpoint times, not "now".
    assert journey.start_date < journey.end_date

    # Default path (no opt-in) must also parse cleanly.
    default_journey = GPXParser().parse(gpx_with_timeless_markers)
    assert len(default_journey.waypoints) == 2


def test_include_waypoints_opt_in_folds_timed_wpt(gpx_with_far_wpt: Path):
    """Opt-in: with include_waypoints=True a *timed* <wpt> is folded in."""
    journey = GPXParser(include_waypoints=True).parse(gpx_with_far_wpt)

    assert len(journey.waypoints) == 3
    coords = {(w.latitude, w.longitude) for w in journey.waypoints}
    assert (60.0, -10.0) in coords


def test_trackpoint_gpx_parses_unchanged(sample_gpx_file: Path):
    """(c) Regression: a well-formed trackpoint GPX still parses fully."""
    journey = GPXParser().parse(sample_gpx_file)

    assert len(journey.waypoints) == 3
    assert journey.waypoints[0].latitude == 40.0
    assert journey.waypoints[-1].latitude == 40.2
    assert journey.start_date < journey.end_date
