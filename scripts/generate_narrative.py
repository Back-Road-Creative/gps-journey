#!/usr/bin/env python3
"""
Generate GPS-derived narrative for any journey.

Produces human-readable narratives with actual place names, roads, and POIs.
"""

import argparse
import importlib.util
import os
import sys
import time
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gps_journey.analysis.route_analyzer import RouteAnalyzer
from gps_journey.core.processor import JourneyProcessor
from gps_journey.geocoding.cache import GeocodingCache
from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient

# =============================================================================
# IntelDB Integration (optional)
# =============================================================================

# Off unless configured. ``INTEL_SCRIPTS_DIR`` names the directory that holds
# ``intel_db.py`` and ``INTEL_DB_PATH`` names the database to record into; the
# narrative is only recorded when both are set.
_INTEL_SCRIPTS_DIR = os.getenv("INTEL_SCRIPTS_DIR", "")

# Platform label stored with each recorded run; ``INTEL_PLATFORM`` overrides it.
_DEFAULT_INTEL_PLATFORM = "gps-journey"


def _get_intel_db(db_path: str):
    """Load IntelDB from ``_INTEL_SCRIPTS_DIR/intel_db.py``; returns None on any failure.

    Returns None, with a warning, when ``INTEL_SCRIPTS_DIR`` is not configured.

    Loaded by file path, never by module name: a plain ``from intel_db import``
    after a sys.path insert is satisfied by any ``intel_db`` already in
    sys.modules or earlier on sys.path, so a missing configured file could
    still produce a database. Nothing is added to sys.path or sys.modules.
    """
    if not _INTEL_SCRIPTS_DIR:
        print("WARNING: Could not import IntelDB: INTEL_SCRIPTS_DIR is not set", file=sys.stderr)
        return None
    module_path = Path(_INTEL_SCRIPTS_DIR) / "intel_db.py"
    if not module_path.is_file():
        print(f"WARNING: Could not import IntelDB: {module_path} not found", file=sys.stderr)
        return None
    spec = importlib.util.spec_from_file_location("intel_db", module_path)
    if spec is None or spec.loader is None:
        print(f"WARNING: Could not import IntelDB: no loader for {module_path}", file=sys.stderr)
        return None
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"WARNING: Could not import IntelDB from {module_path}: {exc}", file=sys.stderr)
        return None
    try:
        return module.IntelDB(db_path)
    except Exception as exc:
        print(f"WARNING: Could not open IntelDB at {db_path!r}: {exc}", file=sys.stderr)
        return None


def _log_narrative_to_intel_db(title: str, narrative: str, output_path: str) -> None:
    """Record a completed GPS narrative in IntelDB (non-fatal; a no-op unless configured)."""
    db_path = os.getenv("INTEL_DB_PATH", "")
    if not db_path:
        return
    db = _get_intel_db(db_path)
    if db is None:
        return
    try:
        from datetime import datetime

        platform = os.getenv("INTEL_PLATFORM") or _DEFAULT_INTEL_PLATFORM
        run_id = db.start_scrape_run(platform, source_name=title)
        date_str = datetime.now().strftime("%Y-%m-%d")
        # Use first 500 chars of narrative as summary (skip the markdown header)
        lines = [
            line for line in narrative.splitlines() if line.strip() and not line.startswith("#")
        ]
        preview = " ".join(lines)[:500]
        summary = preview if preview else f"GPS narrative: {title}"
        db.upsert_news_item(
            date=date_str,
            summary=summary,
            article_links=[output_path] if output_path else [],
            source_count=1,
        )
        db.finish_scrape_run(run_id, items_found=1, items_imported=1)
    except Exception as exc:
        print(f"WARNING: IntelDB write failed for {title!r}: {exc}", file=sys.stderr)
    finally:
        db.close()


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in km."""
    R = 6371
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def detect_stops(waypoints, min_duration_min=15):
    """Detect significant stops."""
    stops = []
    i = 0
    while i < len(waypoints) - 1:
        current = waypoints[i]
        j = i + 1
        while j < len(waypoints):
            if (
                haversine(
                    current.latitude,
                    current.longitude,
                    waypoints[j].latitude,
                    waypoints[j].longitude,
                )
                > 0.05
            ):
                break
            j += 1

        if j > i + 1:
            duration_min = int(
                (waypoints[j - 1].timestamp - current.timestamp).total_seconds() / 60
            )
            if duration_min >= min_duration_min:
                stops.append(
                    {
                        "time": current.timestamp,
                        "duration": duration_min,
                        "lat": current.latitude,
                        "lon": current.longitude,
                    }
                )
        i = j if j > i + 1 else i + 1
    return stops


def clean_location_name(location: str) -> str:
    """Remove administrative suffixes from location names."""
    if not location:
        return location

    suffixes = [
        " Urban Electoral Division",
        " Electoral Division",
        " Urban ED",
        " ED",
        " Urban",
    ]

    cleaned = location
    for suffix in suffixes:
        if cleaned.lower().endswith(suffix.lower()):
            cleaned = cleaned[: len(cleaned) - len(suffix)].strip()
            break

    return cleaned


def generate_narrative(gpx_file: Path, title: str, cache_path: Path) -> str:
    """Generate complete narrative with place names and roads."""
    # Imported lazily so the module stays importable without the full
    # gps_journey package on the path (mirrors the test isolation stubs).
    from gps_journey.core.models import local_day, to_local

    # Parse
    print(f"Parsing {gpx_file.name}...")
    processor = JourneyProcessor(geocoding_enabled=True, geocoding_cache_path=cache_path)
    journey = processor.process(gpx_file)
    print(f"✓ {len(journey.waypoints):,} waypoints")
    print()

    # Group by day. GPX times are UTC; bucket by longitude-local day so an
    # evening drive lands under its own calendar date, not the UTC one.
    by_day = defaultdict(list)
    for w in journey.waypoints:
        by_day[local_day(w.timestamp, w.longitude)].append(w)

    # Initialize geocoder
    cache = GeocodingCache(cache_path, ttl_days=90)
    geocoder = NominatimRoadsClient(cache=cache, rate_limit=1.0)

    # Estimate geocoding
    total_estimates = len(by_day) * 2
    for waypoints in by_day.values():
        stops = detect_stops(waypoints, 15)
        total_estimates += len(stops)
        total_estimates += len(waypoints) // 200

    print(f"Estimated: ~{total_estimates} locations to geocode")
    print(f"Estimated time: ~{int(total_estimates * 1.1 / 60)} minutes")
    print()

    # Build narrative
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        f"**Duration:** {journey.duration_days} days | **Distance:** {journey.statistics.total_distance_km:,.0f} km"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    api_calls = 0
    start_time = time.time()

    for day_num, (date, waypoints) in enumerate(sorted(by_day.items()), 1):
        print(f"Day {day_num}/{len(by_day)} ({date})...", flush=True)

        first, last = waypoints[0], waypoints[-1]
        day_dist = sum(
            haversine(
                waypoints[i].latitude,
                waypoints[i].longitude,
                waypoints[i + 1].latitude,
                waypoints[i + 1].longitude,
            )
            for i in range(len(waypoints) - 1)
        )
        duration_h = (last.timestamp - first.timestamp).total_seconds() / 3600

        # Geocode start location
        try:
            start_geo = geocoder.reverse_geocode_detailed(first.latitude, first.longitude)
            start_name = (
                start_geo.get("isolated_dwelling")
                or start_geo.get("hamlet")
                or start_geo.get("locality")
                or start_geo.get("village")
                or start_geo.get("city_district")
                or start_geo.get("suburb")
                or start_geo.get("town")
                or start_geo.get("city")
            )
            start_name = clean_location_name(start_name)
            api_calls += 1
        except Exception as e:
            start_name = None
            print(f"  Error geocoding start: {e}")

        # Geocode end location
        try:
            end_geo = geocoder.reverse_geocode_detailed(last.latitude, last.longitude)
            end_name = (
                end_geo.get("isolated_dwelling")
                or end_geo.get("hamlet")
                or end_geo.get("locality")
                or end_geo.get("village")
                or end_geo.get("city_district")
                or end_geo.get("suburb")
                or end_geo.get("town")
                or end_geo.get("city")
            )
            end_name = clean_location_name(end_name)
            api_calls += 1
        except Exception as e:
            end_name = None
            print(f"  Error geocoding end: {e}")

        # Get roads via RouteAnalyzer
        try:
            analyzer = RouteAnalyzer(geocoder=geocoder, sample_interval=200)
            roads = analyzer.get_road_segments(waypoints)
            api_calls += len(waypoints) // 200
            road_list = list(set(r["road"] for r in roads if r["road"]))[:3]
            # Keep national (N) and regional (R) road references, e.g. N59, R312.
            main_roads = [r for r in road_list if r and (r.startswith("N") or r.startswith("R"))]
        except Exception:
            main_roads = []

        # Get towns passed through
        try:
            towns_passed = analyzer.get_towns_passed_through(waypoints)
            town_names = [t["name"] for t in towns_passed if t["name"]][:3]
        except Exception:
            town_names = []

        # Detect POI stops only
        stops = detect_stops(waypoints, 15)
        poi_stops = []
        for stop in stops:
            try:
                geo = geocoder.reverse_geocode_detailed(stop["lat"], stop["lon"])
                poi_name = geo.get("poi_name")
                if poi_name:
                    poi_stops.append({**stop, "poi_name": poi_name})
                api_calls += 1
            except Exception:
                continue

        # Build daily narrative
        lines.append(f"## {date.strftime('%A, %B %d')}")
        lines.append("")

        start_clock = to_local(first.timestamp, first.longitude).strftime("%I:%M %p")
        if start_name:
            narrative = f"We left {start_name} at {start_clock}"
        else:
            narrative = f"We left at {start_clock}"

        if main_roads:
            narrative += f" and drove along {', '.join(main_roads)}"

        if town_names:
            narrative += f" through {', '.join(town_names)}"

        for stop in poi_stops:
            stop_clock = to_local(stop["time"], stop["lon"]).strftime("%I:%M %p")
            narrative += (
                f". At {stop_clock} we stopped at {stop['poi_name']} for {stop['duration']} minutes"
            )

        end_clock = to_local(last.timestamp, last.longitude).strftime("%I:%M %p")
        if end_name:
            narrative += f", arriving in {end_name} at {end_clock}."
        else:
            narrative += f", arriving at {end_clock}."

        lines.append(narrative)
        lines.append("")
        lines.append(f"Distance: {day_dist:.0f} km | Duration: {duration_h:.1f} hours")
        lines.append("")

        elapsed = time.time() - start_time
        print(f"  ✓ Day {day_num} complete ({api_calls} API calls, {elapsed:.0f}s elapsed)")

    print()
    print(f"✓ Total API calls: {api_calls}")
    print(f"✓ Total time: {time.time() - start_time:.0f} seconds")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate GPS narrative")
    parser.add_argument("--gpx", required=True, help="Path to GPX file")
    parser.add_argument("--title", required=True, help="Journey title")
    parser.add_argument("--output", required=True, help="Output markdown file")
    parser.add_argument("--cache", default=".cache/geocode_cache.json", help="Geocoding cache path")

    args = parser.parse_args()

    gpx_file = Path(args.gpx)
    output_file = Path(args.output)
    cache_path = Path(args.cache)

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(f"GENERATING: {args.title}")
    print("=" * 70)
    print()

    narrative = generate_narrative(gpx_file, args.title, cache_path)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(narrative)

    print()
    print(f"✓ Narrative saved to: {output_file}")

    _log_narrative_to_intel_db(args.title, narrative, str(output_file))


if __name__ == "__main__":
    main()
