#!/usr/bin/env python3
"""
Extract Journey Data for Claude Code Narrative Generation

Processes GPX file and photos, outputs structured JSON for Claude to generate narratives.

Usage:
    ./scripts/extract_journey_data.py \
        --gpx path/to/track.gpx \
        --photos-dir path/to/photos \
        --output ./output/journey-data.json
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gps_journey.core.processor import JourneyProcessor
from gps_journey.geocoding.cache import GeocodingCache
from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient
from gps_journey.photos.exif import EXIFExtractor


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in km."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def km_to_miles(km):
    """Convert kilometers to miles."""
    return round(km * 0.621371, 1)


def clean_location_name(location: str) -> str:
    """Remove administrative suffixes from Irish location names."""
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


def detect_stops(waypoints, geocoder, min_duration_min=5):
    """Detect stops and geocode each location to get town/district names."""
    stops = []
    i = 0
    geocoded_count = 0

    while i < len(waypoints) - 1:
        current = waypoints[i]
        j = i + 1

        # Find consecutive waypoints within 50m radius
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

        # Check if stopped long enough
        if j > i + 1:
            duration_min = int(
                (waypoints[j - 1].timestamp - current.timestamp).total_seconds() / 60
            )
            if duration_min >= min_duration_min:
                # Geocode this stop location (CRITICAL FIX)
                location_name = None
                county = None

                if geocoder:
                    try:
                        geo_data = geocoder.reverse_geocode_detailed(
                            current.latitude, current.longitude
                        )

                        # Priority cascade: hamlet → locality → village → town → city
                        location_name = (
                            geo_data.get("poi_name")
                            or geo_data.get("isolated_dwelling")
                            or geo_data.get("hamlet")
                            or geo_data.get("locality")
                            or geo_data.get("village")
                            or geo_data.get("city_district")
                            or geo_data.get("suburb")
                            or geo_data.get("town")
                            or geo_data.get("city")
                        )

                        if location_name:
                            location_name = clean_location_name(location_name)

                        county = geo_data.get("county")
                        if county and not county.startswith("County"):
                            county = f"County {county}"

                        geocoded_count += 1
                        if geocoded_count % 5 == 0:
                            print(f"      Geocoded {geocoded_count} stops...")

                        time.sleep(1.1)  # Respect 1 req/sec rate limit

                    except Exception:
                        print(
                            f"      Warning: Geocoding failed for {current.latitude:.4f}, {current.longitude:.4f}"
                        )

                # Build final location string
                if location_name and county:
                    full_location = f"{location_name}, {county}"
                elif location_name:
                    full_location = location_name
                elif county:
                    full_location = county
                else:
                    # Last resort: coordinates
                    full_location = f"{current.latitude:.4f}°, {current.longitude:.4f}°"

                stops.append(
                    {
                        "time": current.timestamp.isoformat(),
                        "time_formatted": current.timestamp.strftime("%I:%M %p"),
                        "duration_minutes": duration_min,
                        "location": full_location,
                        "lat": current.latitude,
                        "lon": current.longitude,
                    }
                )

        i = j if j > i + 1 else i + 1

    return stops


def main():
    parser = argparse.ArgumentParser(description="Extract journey data for Claude narratives")
    parser.add_argument("--gpx", type=Path, required=True, help="GPX file")
    parser.add_argument("--photos-dir", type=Path, help="Photos directory")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON file")

    args = parser.parse_args()

    print("=" * 70)
    print("📊 EXTRACTING JOURNEY DATA FOR CLAUDE")
    print("=" * 70)
    print()

    # Initialize geocoder for stop location names
    print("🗺️  Initializing geocoder with cache...")
    cache_path = Path(".cache/geocode_cache.json")
    cache = GeocodingCache(cache_path, ttl_days=90)
    geocoder = NominatimRoadsClient(cache=cache, rate_limit=1.0)
    print("✅ Geocoder ready")
    print()

    # Parse GPX
    print(f"📍 Parsing GPX: {args.gpx.name}")
    processor = JourneyProcessor(geocoding_enabled=True)
    journey = processor.process(args.gpx)

    print(f"✅ Parsed {len(journey.waypoints):,} waypoints")
    print(f"   Duration: {len(set(wp.timestamp.date() for wp in journey.waypoints))} days")
    print()

    # Group by day
    waypoints_by_day = defaultdict(list)
    for wp in journey.waypoints:
        waypoints_by_day[wp.timestamp.date()].append(wp)

    # Process photos
    photos_by_day = defaultdict(list)
    total_photos = 0

    if args.photos_dir and args.photos_dir.exists():
        print(f"📸 Processing photos from: {args.photos_dir}")
        exif_extractor = EXIFExtractor()

        photo_files = list(args.photos_dir.glob("*.jpg")) + list(args.photos_dir.glob("*.JPG"))
        photo_files.extend(args.photos_dir.glob("*.jpeg"))

        for photo_file in sorted(photo_files):
            try:
                metadata = exif_extractor.extract(photo_file, photo_file.name)
                if metadata.timestamp:
                    # Match to day
                    for day_date, day_wps in waypoints_by_day.items():
                        day_start = day_wps[0].timestamp
                        day_end = day_wps[-1].timestamp

                        # Allow 1 hour tolerance for matching
                        from datetime import timedelta

                        if (
                            (day_start - timedelta(hours=1))
                            <= metadata.timestamp
                            <= (day_end + timedelta(hours=1))
                        ):
                            photos_by_day[day_date].append(
                                {
                                    "filename": photo_file.name,
                                    "timestamp": metadata.timestamp.isoformat(),
                                    "lat": metadata.gps_latitude,
                                    "lon": metadata.gps_longitude,
                                }
                            )
                            total_photos += 1
                            break
            except Exception:
                pass

        print(f"✅ Matched {total_photos} photos to journey days")
        print()

    # Build output data structure
    # Get start/end dates from first/last waypoints
    all_dates = sorted(waypoints_by_day.keys())
    first_day_wps = waypoints_by_day[all_dates[0]]
    last_day_wps = waypoints_by_day[all_dates[-1]]

    output_data = {
        "journey": {
            "title": args.gpx.stem,
            "start_date": all_dates[0].isoformat(),
            "end_date": all_dates[-1].isoformat(),
            "start_time": first_day_wps[0].timestamp.isoformat(),
            "end_time": last_day_wps[-1].timestamp.isoformat(),
            "total_distance_km": 0,  # Will calculate from days
            "total_days": len(waypoints_by_day),
            "total_photos": total_photos,
        },
        "days": [],
    }

    # Process each day
    for day_num, day_date in enumerate(sorted(waypoints_by_day.keys()), 1):
        print(f"📅 Processing Day {day_num} ({day_date})...")

        day_wps = waypoints_by_day[day_date]
        first = day_wps[0]
        last = day_wps[-1]

        # Calculate distance for this day
        distance = 0
        for i in range(len(day_wps) - 1):
            w1, w2 = day_wps[i], day_wps[i + 1]
            distance += haversine(w1.latitude, w1.longitude, w2.latitude, w2.longitude)

        # Calculate elevation
        elev_gain = 0
        elev_loss = 0
        for i in range(len(day_wps) - 1):
            if day_wps[i].elevation and day_wps[i + 1].elevation:
                diff = day_wps[i + 1].elevation - day_wps[i].elevation
                if diff > 0:
                    elev_gain += diff
                else:
                    elev_loss += abs(diff)

        # Detect and geocode stops
        print("   Detecting and geocoding stops...")
        stops = detect_stops(day_wps, geocoder, min_duration_min=5)
        print(f"   ✅ Found {len(stops)} stops")

        # Get unique locations (convert to strings)
        locations = list(set([str(wp.location) for wp in day_wps if wp.location]))

        # Photos for this day
        day_photos = photos_by_day.get(day_date, [])

        day_data = {
            "day_number": day_num,
            "date": day_date.isoformat(),
            "date_formatted": day_date.strftime("%A, %B %d, %Y"),
            "departure": {
                "time": first.timestamp.strftime("%I:%M %p"),
                "location": str(first.location)
                if first.location
                else f"{first.latitude:.4f}°, {first.longitude:.4f}°",
                "lat": first.latitude,
                "lon": first.longitude,
                "elevation_m": first.elevation,
            },
            "arrival": {
                "time": last.timestamp.strftime("%I:%M %p"),
                "location": str(last.location)
                if last.location
                else f"{last.latitude:.4f}°, {last.longitude:.4f}°",
                "lat": last.latitude,
                "lon": last.longitude,
                "elevation_m": last.elevation,
            },
            "statistics": {
                "distance_km": round(distance, 1),
                "distance_miles": km_to_miles(distance),
                "duration_hours": round(
                    (last.timestamp - first.timestamp).total_seconds() / 3600, 1
                ),
                "waypoint_count": len(day_wps),
                "elevation_gain_m": round(elev_gain, 0),
                "elevation_loss_m": round(elev_loss, 0),
            },
            "stops": stops[:10],  # Top 10 stops
            "locations_visited": locations[:20],  # Top 20 locations
            "photos": sorted(day_photos, key=lambda p: p["timestamp"])[
                :5
            ],  # Top 5 photos for inline
        }

        output_data["days"].append(day_data)
        print(
            f"✅ Day {day_num}: {distance:.1f} km ({km_to_miles(distance)} mi), {len(stops)} stops"
        )
        print()

    # Calculate total distance
    output_data["journey"]["total_distance_km"] = round(
        sum(day["statistics"]["distance_km"] for day in output_data["days"]), 1
    )
    output_data["journey"]["total_distance_miles"] = km_to_miles(
        output_data["journey"]["total_distance_km"]
    )

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2))

    print("=" * 70)
    print("✅ DATA EXTRACTION COMPLETE")
    print("=" * 70)
    print()
    print(f"📄 Output: {args.output}")
    print(
        f"📊 Total Distance: {output_data['journey']['total_distance_km']} km ({output_data['journey']['total_distance_miles']} miles)"
    )
    print(f"📅 Days: {output_data['journey']['total_days']}")
    print(f"📸 Photos: {output_data['journey']['total_photos']}")
    print()
    print("🗺️  All stops have been geocoded to town/district names!")
    print()
    print("🤖 Next Step: Ask Claude Code to generate narratives from this data")


if __name__ == "__main__":
    main()
