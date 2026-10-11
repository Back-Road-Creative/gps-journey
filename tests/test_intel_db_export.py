"""Tests for scripts/generate_narrative.py: the optional IntelDB integration and the narrative builder."""

import importlib.util
import inspect
import math
import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Stub gps_journey and its sub-modules before importing generate_narrative
_gps_journey = types.ModuleType("gps_journey")
sys.modules.setdefault("gps_journey", _gps_journey)
for _sub in (
    "gps_journey.analysis",
    "gps_journey.analysis.route_analyzer",
    "gps_journey.core",
    "gps_journey.core.processor",
    "gps_journey.geocoding",
    "gps_journey.geocoding.cache",
    "gps_journey.geocoding.nominatim_roads",
):
    sys.modules.setdefault(_sub, types.ModuleType(_sub))

# Provide the specific names imported by generate_narrative
sys.modules["gps_journey.analysis.route_analyzer"].RouteAnalyzer = object
sys.modules["gps_journey.core.processor"].JourneyProcessor = object
sys.modules["gps_journey.geocoding.cache"].GeocodingCache = object
sys.modules["gps_journey.geocoding.nominatim_roads"].NominatimRoadsClient = object

# Add scripts/ to path so generate_narrative can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import generate_narrative as gn  # noqa: E402

# Remove stub modules so real gps_journey packages can be imported by other tests.
# generate_narrative already holds references from its module-level imports.
for _stub_name in (
    "gps_journey",
    "gps_journey.analysis",
    "gps_journey.analysis.route_analyzer",
    "gps_journey.core",
    "gps_journey.core.processor",
    "gps_journey.geocoding",
    "gps_journey.geocoding.cache",
    "gps_journey.geocoding.nominatim_roads",
):
    _m = sys.modules.get(_stub_name)
    if _m is not None and not getattr(_m, "__file__", None):
        del sys.modules[_stub_name]

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "generate_narrative.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intel_db(path: str) -> None:
    """Create a minimal IntelDB-compatible SQLite database."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            source_name TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            items_found INTEGER DEFAULT 0,
            items_imported INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            summary TEXT,
            source_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


class _SimpleIntelDB:
    """Minimal IntelDB backed by a real SQLite file."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def start_scrape_run(self, platform: str, source_name: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO scrape_runs (platform, source_name, started_at, status) "
            "VALUES (?, ?, datetime('now'), 'running')",
            (platform, source_name),
        )
        self.conn.commit()
        return cur.lastrowid

    def upsert_news_item(
        self, date: str, summary: str, article_links: list, source_count: int = 0
    ) -> None:
        self.conn.execute(
            "INSERT INTO news_items (date, summary, source_count) VALUES (?, ?, ?)",
            (date, summary, source_count),
        )
        self.conn.commit()

    def finish_scrape_run(self, run_id: int, items_found: int = 0, items_imported: int = 0) -> None:
        self.conn.execute(
            "UPDATE scrape_runs SET status='success', finished_at=datetime('now'), "
            "items_found=?, items_imported=? WHERE id=?",
            (items_found, items_imported, run_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class _DecoyIntelDB(_SimpleIntelDB):
    """An IntelDB that is NOT the configured file -- the loader must never return it."""

    SOURCE = "decoy"


_FAILING_INTEL_DB_SOURCE = (
    "class IntelDB:\n    def __init__(self, path):\n        raise RuntimeError('Cannot open')\n"
)


def _simple_intel_db_source(marker: str = "configured") -> str:
    """Source of a file-based fake ``intel_db.py`` whose IntelDB is _SimpleIntelDB."""
    return (
        "import sqlite3\n\n\n"
        + inspect.getsource(_SimpleIntelDB)
        + f"\n\nclass IntelDB(_SimpleIntelDB):\n    SOURCE = {marker!r}\n"
    )


def _write_intel_module(directory: Path, source: str) -> Path:
    """Write ``intel_db.py`` into ``directory`` and return the directory.

    The loader reads the file at ``_INTEL_SCRIPTS_DIR/intel_db.py``; a fake
    injected into ``sys.modules`` is exactly what it must ignore.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "intel_db.py").write_text(source)
    return directory


# ---------------------------------------------------------------------------
# Tests: _get_intel_db
# ---------------------------------------------------------------------------


def test_get_intel_db_returns_none_on_missing_module(tmp_path):
    """Returns None without raising when intel_db is not importable."""
    bad_dir = str(tmp_path / "nonexistent")
    with patch.dict(sys.modules), patch.object(gn, "_INTEL_SCRIPTS_DIR", bad_dir):
        sys.modules.pop("intel_db", None)
        result = gn._get_intel_db(str(tmp_path / "db.sqlite"))
    assert result is None


def test_get_intel_db_returns_instance_when_available(tmp_path):
    """Returns a DB instance when the configured intel_db.py can be loaded."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    with patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)):
        db = gn._get_intel_db(db_path)
    assert db is not None
    db.close()


def test_get_intel_db_ignores_cached_intel_db_module(tmp_path):
    """A missing configured file returns None even when sys.modules holds an ``intel_db``.

    A plain import would be satisfied by an ``intel_db`` another test left in
    ``sys.modules``, so a missing configured directory would still produce a
    database.
    """
    decoy = types.ModuleType("intel_db")
    decoy.IntelDB = _DecoyIntelDB
    missing_dir = str(tmp_path / "missing")
    with (
        patch.dict(sys.modules, {"intel_db": decoy}),
        patch.object(sys, "path", list(sys.path)),
        patch.object(gn, "_INTEL_SCRIPTS_DIR", missing_dir),
    ):
        result = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert result is None


def test_get_intel_db_ignores_intel_db_elsewhere_on_sys_path(tmp_path, monkeypatch):
    """A missing configured file returns None even when another ``intel_db.py`` is importable.

    The loader must read ``_INTEL_SCRIPTS_DIR/intel_db.py`` by file path, never
    fall through to whatever ``intel_db`` a sys.path search finds; otherwise
    the result would depend on which directories earlier code put on sys.path.
    """
    decoy_dir = _write_intel_module(tmp_path / "decoy", _simple_intel_db_source("decoy"))
    monkeypatch.syspath_prepend(str(decoy_dir))
    missing_dir = str(tmp_path / "missing")
    with patch.dict(sys.modules), patch.object(gn, "_INTEL_SCRIPTS_DIR", missing_dir):
        sys.modules.pop("intel_db", None)
        result = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert result is None


def test_get_intel_db_loads_configured_file_over_cached_module(tmp_path):
    """The configured file wins over an ``intel_db`` already cached in sys.modules."""
    decoy = types.ModuleType("intel_db")
    decoy.IntelDB = _DecoyIntelDB
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source("configured"))
    with (
        patch.dict(sys.modules, {"intel_db": decoy}),
        patch.object(sys, "path", list(sys.path)),
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
    ):
        db = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert db is not None
    assert db.SOURCE == "configured"
    db.close()


def test_get_intel_db_leaves_sys_path_and_sys_modules_untouched(tmp_path):
    """Loading IntelDB neither inserts into sys.path nor caches ``intel_db`` in sys.modules."""
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    with patch.dict(sys.modules), patch.object(sys, "path", list(sys.path)):
        path_before = list(sys.path)
        module_before = sys.modules.get("intel_db")
        with patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)):
            db = gn._get_intel_db(str(tmp_path / "intel.db"))
        path_after = list(sys.path)
        module_after = sys.modules.get("intel_db")
    assert db is not None
    db.close()
    assert path_after == path_before
    assert module_after is module_before


def test_get_intel_db_returns_none_when_configured_module_fails_to_load(tmp_path, capsys):
    """A configured ``intel_db.py`` that raises while executing returns None, not the error."""
    intel_dir = _write_intel_module(tmp_path / "intel", "raise RuntimeError('broken intel_db')\n")
    with patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)):
        result = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert result is None
    assert "broken intel_db" in capsys.readouterr().err


def test_get_intel_db_returns_none_when_no_loader_for_file(tmp_path, capsys):
    """Returns None when importlib yields no spec for the configured file."""
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    no_spec = types.SimpleNamespace(
        util=types.SimpleNamespace(spec_from_file_location=lambda name, location: None)
    )
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.object(gn, "importlib", no_spec),
    ):
        result = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert result is None
    assert "no loader" in capsys.readouterr().err


_SCHEMA_INTEL_DB_SOURCE = """
import sqlite3


class IntelDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS scrape_runs (id INTEGER PRIMARY KEY)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS news_items (id INTEGER PRIMARY KEY)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY)")
        self.conn.commit()

    def close(self):
        self.conn.close()
"""


def test_get_intel_db_loads_a_module_that_applies_its_own_schema(tmp_path):
    """A module written to the configured directory loads by file path and applies its schema."""
    intel_dir = _write_intel_module(tmp_path / "intel", _SCHEMA_INTEL_DB_SOURCE)
    with patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)):
        db = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert db is not None
    tables = {
        row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    db.close()
    assert {"scrape_runs", "news_items", "models"} <= tables


def _load_fresh_script():
    """Execute a private copy of the script so its import-time configuration is re-read."""
    spec = importlib.util.spec_from_file_location("generate_narrative_fresh", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intel_scripts_dir_default_is_unset(monkeypatch):
    """With no INTEL_SCRIPTS_DIR the integration has no directory to load from."""
    monkeypatch.delenv("INTEL_SCRIPTS_DIR", raising=False)
    configured = _load_fresh_script()._INTEL_SCRIPTS_DIR
    assert configured == ""


def test_intel_scripts_dir_env_override_still_applies(monkeypatch, tmp_path):
    """INTEL_SCRIPTS_DIR keeps its name and overrides the default."""
    monkeypatch.setenv("INTEL_SCRIPTS_DIR", str(tmp_path))
    configured = _load_fresh_script()._INTEL_SCRIPTS_DIR
    assert configured == str(tmp_path)


def test_get_intel_db_returns_none_and_warns_when_not_configured(tmp_path, capsys):
    """An unset directory is 'off': no database, a warning, and nothing read from the cwd."""
    (tmp_path / "intel_db.py").write_text(_simple_intel_db_source())
    with patch.object(gn, "_INTEL_SCRIPTS_DIR", ""), patch.object(Path, "cwd", lambda: tmp_path):
        result = gn._get_intel_db(str(tmp_path / "intel.db"))
    assert result is None
    assert "INTEL_SCRIPTS_DIR is not set" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Tests: _log_narrative_to_intel_db
# ---------------------------------------------------------------------------


def test_log_narrative_noop_when_no_env(tmp_path):
    """No-op (no raise, no database lookup) when INTEL_DB_PATH is not set."""
    with (
        patch.dict(os.environ),
        patch.object(gn, "_get_intel_db", side_effect=AssertionError("must not load")),
    ):
        os.environ.pop("INTEL_DB_PATH", None)
        gn._log_narrative_to_intel_db("Example Journey", "## Day 1\nWe drove.", "")


def test_log_narrative_noop_when_scripts_dir_not_configured(tmp_path, capsys):
    """INTEL_DB_PATH alone is not enough: with no scripts directory nothing is recorded."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", ""),
        patch.dict(os.environ, {"INTEL_DB_PATH": db_path}),
    ):
        gn._log_narrative_to_intel_db("Example Journey", "## Day 1\nWe drove.", "")
    conn = sqlite3.connect(db_path)
    runs = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
    conn.close()
    assert runs == 0
    assert "INTEL_SCRIPTS_DIR is not set" in capsys.readouterr().err


def test_log_narrative_writes_scrape_run(tmp_path):
    """A scrape_run row is created with the default platform label 'gps-journey'."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.dict(os.environ, {"INTEL_DB_PATH": db_path}),
    ):
        gn._log_narrative_to_intel_db("Example Journey", "## Day 1\nWe drove.", "/out/journey.md")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM scrape_runs").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["platform"] == "gps-journey"
    assert rows[0]["status"] == "success"
    assert rows[0]["items_imported"] == 1


def test_log_narrative_platform_env_override(tmp_path):
    """INTEL_PLATFORM overrides the platform label stored with the run."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.dict(os.environ, {"INTEL_DB_PATH": db_path, "INTEL_PLATFORM": "custom-platform"}),
    ):
        gn._log_narrative_to_intel_db("Example Journey", "## Day 1\nWe drove.", "")

    conn = sqlite3.connect(db_path)
    platform = conn.execute("SELECT platform FROM scrape_runs").fetchone()[0]
    conn.close()
    assert platform == "custom-platform"


def test_log_narrative_source_name_is_title(tmp_path):
    """source_name in scrape_runs equals the journey title."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.dict(os.environ, {"INTEL_DB_PATH": db_path}),
    ):
        gn._log_narrative_to_intel_db("Second Example", "Some narrative text.", "")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT source_name FROM scrape_runs").fetchone()
    conn.close()
    assert row["source_name"] == "Second Example"


def test_log_narrative_summary_skips_header_lines(tmp_path):
    """Summary is built from non-header lines of the narrative."""
    db_path = str(tmp_path / "intel.db")
    _make_intel_db(db_path)
    intel_dir = _write_intel_module(tmp_path / "intel", _simple_intel_db_source())
    narrative = "# Example Journey\n\n## Day 1\nWe left Dublin at 09:00 AM."
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.dict(os.environ, {"INTEL_DB_PATH": db_path}),
    ):
        gn._log_narrative_to_intel_db("Example Journey", narrative, "")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT summary FROM news_items").fetchone()
    conn.close()
    # Body text (non-header) is present in summary
    assert "We left Dublin" in row["summary"]


def test_log_narrative_noop_on_bad_db_path(tmp_path):
    """Non-fatal when DB can't be opened."""
    intel_dir = _write_intel_module(tmp_path / "intel", _FAILING_INTEL_DB_SOURCE)
    with (
        patch.object(gn, "_INTEL_SCRIPTS_DIR", str(intel_dir)),
        patch.dict(os.environ, {"INTEL_DB_PATH": "/nonexistent/db.sqlite"}),
    ):
        gn._log_narrative_to_intel_db("Test Journey", "Some text.", "")


# ---------------------------------------------------------------------------
# Tests: narrative helpers and generate_narrative
# ---------------------------------------------------------------------------

# Reverse-geocode answers by coordinate; anything north of 60N is "down".
_PLACES = {
    (54.10, -9.20): {"village": "Ballina Urban Electoral Division"},
    (54.20, -9.40): {"poi_name": "Nephin Cafe"},
    (54.30, -9.60): {"town": "Belmullet"},
}

# 10:00 UTC; at these longitudes the local offset is round(lon / 15) = -1 h.
_DAY1 = datetime(2031, 3, 3, 10, 0)
_DAY2 = datetime(2031, 3, 4, 10, 0)


def _waypoint(lat, lon, when):
    return types.SimpleNamespace(latitude=lat, longitude=lon, timestamp=when)


def _day1_waypoints():
    """Leave Ballina, park 20 minutes at the cafe, arrive in Belmullet."""
    return [
        _waypoint(54.10, -9.20, _DAY1),
        _waypoint(54.20, -9.40, _DAY1 + timedelta(minutes=30)),
        _waypoint(54.20, -9.40, _DAY1 + timedelta(minutes=40)),
        _waypoint(54.20, -9.40, _DAY1 + timedelta(minutes=50)),
        _waypoint(54.30, -9.60, _DAY1 + timedelta(minutes=90)),
    ]


class _FakeGeocoder:
    def __init__(self, cache, rate_limit):
        self.rate_limit = rate_limit

    def reverse_geocode_detailed(self, lat, lon):
        if lat >= 60:
            raise RuntimeError("geocoder down")
        return _PLACES.get((lat, lon), {})


class _FakeRouteAnalyzer:
    def __init__(self, geocoder, sample_interval):
        self.sample_interval = sample_interval

    def get_road_segments(self, waypoints):
        if waypoints[0].latitude >= 60:
            raise RuntimeError("roads down")
        return [{"road": "N59"}, {"road": "R312"}, {"road": "L1105"}, {"road": None}]

    def get_towns_passed_through(self, waypoints):
        if waypoints[0].latitude >= 60:
            raise RuntimeError("towns down")
        return [{"name": "Crossmolina"}, {"name": None}]


def test_haversine_one_degree_of_latitude():
    assert gn.haversine(0, 0, 1, 0) == pytest.approx(6371 * math.radians(1))


def test_detect_stops_reports_a_dwell_at_or_over_the_threshold():
    waypoints = _day1_waypoints()
    assert gn.detect_stops(waypoints, 15) == [
        {"time": _DAY1 + timedelta(minutes=30), "duration": 20, "lat": 54.20, "lon": -9.40}
    ]
    assert gn.detect_stops(waypoints, 25) == []


def test_clean_location_name_strips_one_administrative_suffix():
    assert gn.clean_location_name("Ballina Urban Electoral Division") == "Ballina"
    assert gn.clean_location_name("Westport") == "Westport"
    assert gn.clean_location_name("") == ""


def test_generate_narrative_builds_each_day_and_survives_geocoder_failures(tmp_path):
    """Day 1 resolves every name; day 2 (north of 60N) loses every lookup but still renders."""
    waypoints = [
        *_day1_waypoints(),
        _waypoint(61.00, -9.20, _DAY2),
        _waypoint(61.00, -9.20, _DAY2 + timedelta(minutes=20)),
        _waypoint(61.10, -9.20, _DAY2 + timedelta(minutes=60)),
    ]
    journey = types.SimpleNamespace(
        waypoints=waypoints,
        duration_days=2,
        statistics=types.SimpleNamespace(total_distance_km=1234.4),
    )

    class _FakeProcessor:
        def __init__(self, geocoding_enabled, geocoding_cache_path):
            self.cache_path = geocoding_cache_path

        def process(self, gpx_file):
            return journey

    with (
        patch.object(gn, "JourneyProcessor", _FakeProcessor),
        patch.object(gn, "GeocodingCache", lambda path, ttl_days: object()),
        patch.object(gn, "NominatimRoadsClient", _FakeGeocoder),
        patch.object(gn, "RouteAnalyzer", _FakeRouteAnalyzer),
    ):
        text = gn.generate_narrative(
            tmp_path / "trip.gpx", "Example Coast Road", tmp_path / "geocode.json"
        )

    lines = text.split("\n")
    assert lines[0] == "# Example Coast Road"
    assert "**Duration:** 2 days | **Distance:** 1,234 km" in lines

    day1 = lines[lines.index("## Monday, March 03") + 2]
    head = "We left Ballina at 09:00 AM and drove along "
    tail = (
        " through Crossmolina. At 09:30 AM we stopped at Nephin Cafe for 20 minutes,"
        " arriving in Belmullet at 10:30 AM."
    )
    assert day1.startswith(head)
    assert day1.endswith(tail)
    # Only N and R roads are named; their order follows set iteration.
    assert set(day1[len(head) : -len(tail)].split(", ")) == {"N59", "R312"}

    day2 = lines[lines.index("## Tuesday, March 04") + 2]
    assert day2 == "We left at 09:00 AM, arriving at 10:00 AM."
