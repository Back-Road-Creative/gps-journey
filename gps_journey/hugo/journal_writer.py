"""Human-readable journal writer - only meaningful POIs, natural language."""

import logging
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt

from gps_journey.core.models import (
    Journey,
    Waypoint,
    format_distance_km,
    local_day,
    region_label,
    to_local,
    uses_miles,
)
from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient

logger = logging.getLogger(__name__)


class JournalWriter:
    """
    Generate human-readable travel journal from GPS data.

    Rules:
    1. Only mention stops with identifiable POIs (restaurants, hotels, attractions)
    2. Skip coordinate dumps and unknown locations
    3. Write in natural narrative style: "We left... drove along... stopped at..."
    4. Only GPS data facts - no creative embellishment
    5. Read like a human journal, not a data dump
    """

    def __init__(self, geocoder: NominatimRoadsClient | None = None):
        """
        Initialize journal writer.

        Args:
            geocoder: Nominatim client with road-level detail
        """
        self.geocoder = geocoder

    def generate(self, journey: Journey) -> str:
        """
        Generate human-readable journal from journey.

        Args:
            journey: Journey with GPS waypoints

        Returns:
            Natural language journal text
        """
        # Derive region and units from the journey's own geocoded data, not a
        # hardcoded "Ireland"/"km" — this repo publishes journeys worldwide.
        first_wp = journey.waypoints[0] if journey.waypoints else None
        origin = journey.start_location or (first_wp.location if first_wp else None)
        region = region_label(origin)
        miles = uses_miles(origin.country if origin else None)
        month_year = (
            to_local(journey.start_date, first_wp.longitude).strftime("%B %Y")
            if first_wp
            else journey.start_date.strftime("%B %Y")
        )

        lines = []
        default_title = (
            f"{region} Road Trip - {month_year}" if region else f"Road Trip - {month_year}"
        )
        lines.append(f"# {journey.title or default_title}")
        lines.append("")
        distance = format_distance_km(journey.statistics.total_distance_km, miles=miles)
        through = f" through {region}" if region else ""
        lines.append(f"A {journey.duration_days}-day journey covering {distance}{through}.")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Group by day
        waypoints_by_day = self._group_by_day(journey.waypoints)

        # Process each day
        for day_num, (date, waypoints) in enumerate(sorted(waypoints_by_day.items()), 1):
            day_narrative = self._write_day(day_num, date, waypoints, miles=miles)
            if day_narrative:
                lines.extend(day_narrative)

        return "\n".join(lines)

    def _group_by_day(self, waypoints: tuple[Waypoint, ...]) -> dict:
        """Group waypoints by longitude-local calendar day (GPX times are UTC)."""
        by_day = defaultdict(list)
        for w in waypoints:
            by_day[local_day(w.timestamp, w.longitude)].append(w)
        return by_day

    def _write_day(
        self, day_num: int, date, waypoints: list[Waypoint], *, miles: bool = False
    ) -> list[str]:
        """Write natural journal entry for one day."""
        lines = []
        first = waypoints[0]
        last = waypoints[-1]

        # Calculate stats
        day_dist = self._calculate_distance(waypoints)
        duration_hours = (last.timestamp - first.timestamp).total_seconds() / 3600

        # Day header
        day_name = date.strftime("%A")
        lines.append(f"## {day_name}, {date.strftime('%B %d')}")
        lines.append("")

        # Build opening sentence with departure location (times are local)
        start_time = to_local(first.timestamp, first.longitude).strftime("%I:%M %p")
        dep_location = self._get_specific_location(first.location) if first.location else None

        if dep_location:
            narrative = f"We left {dep_location} at {start_time}"
        else:
            narrative = f"We left at {start_time}"

        # Detect and filter meaningful stops (POI only)
        stops = self._detect_stops(waypoints)
        meaningful_stops = self._filter_meaningful_stops(stops)

        # Add stops to narrative (only if identified)
        if meaningful_stops:
            for stop in meaningful_stops:
                stop_time = to_local(stop["time"], stop["lon"]).strftime("%I:%M %p")
                duration = stop["duration"]
                poi_name = stop.get("meaningful_name", "")

                if poi_name:
                    # Add stop to narrative
                    narrative += f". At {stop_time} we stopped at {poi_name} for {duration} minutes"

        # Add arrival with specific location (times are local)
        end_time = to_local(last.timestamp, last.longitude).strftime("%I:%M %p")
        arr_location = self._get_specific_location(last.location) if last.location else None

        if arr_location:
            narrative += f", arriving in {arr_location} at {end_time}."
        else:
            narrative += f", arriving at {end_time}."

        lines.append(narrative)
        lines.append("")

        # Add distance summary (units follow the journey's region)
        lines.append(
            f"Distance: {format_distance_km(day_dist, miles=miles)} "
            f"| Duration: {duration_hours:.1f} hours"
        )
        lines.append("")

        return lines

    def _get_specific_location(self, location) -> str | None:
        """
        Extract most specific location name from Location object.

        Priority: name (POI/village) > city > county
        Returns None if only generic location available.
        """
        if not location:
            return None

        # Prefer name field (village, landmark, POI)
        if location.name:
            return location.name

        # Fall back to city
        if location.city:
            return location.city

        # Skip county-only (too generic)
        return None

    def _detect_stops(self, waypoints: list[Waypoint], min_duration_min: int = 5) -> list[dict]:
        """Detect stops where vehicle was stationary."""
        stops = []
        i = 0

        while i < len(waypoints) - 1:
            current = waypoints[i]
            j = i + 1

            # Find end of stationary period
            while j < len(waypoints):
                dist = self._haversine(
                    current.latitude,
                    current.longitude,
                    waypoints[j].latitude,
                    waypoints[j].longitude,
                )
                if dist > 0.05:  # 50 meters
                    break
                j += 1

            # Check duration
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
                            "waypoint": current,
                        }
                    )

            i = j if j > i + 1 else i + 1

        return stops

    def _filter_meaningful_stops(self, stops: list[dict]) -> list[dict]:
        """
        Filter stops to only meaningful POIs.

        Geocode each stop and keep only if it has a recognized POI.
        Skip unknown locations, bare coordinates, and generic county names.
        """
        if not self.geocoder:
            return []

        meaningful = []

        for stop in stops:
            try:
                geo = self.geocoder.reverse_geocode_detailed(stop["lat"], stop["lon"])

                # Determine if this is meaningful
                poi_name = geo.get("poi_name")
                geo.get("poi")
                road = geo.get("road")
                village = geo.get("village")
                town = geo.get("town")

                # Keep if: POI with name, or village/town (not just county)
                if poi_name:
                    # Definite POI (pub, hotel, attraction, etc.)
                    stop["geo"] = geo
                    stop["meaningful_name"] = poi_name
                    stop["type"] = "poi"
                    meaningful.append(stop)
                elif village or town:
                    # Village or town (not just county) - might be gas stop
                    # Only keep if stop is >10 minutes (likely meaningful)
                    if stop["duration"] >= 10:
                        location = village or town
                        stop["geo"] = geo
                        stop["meaningful_name"] = location
                        stop["type"] = "town"
                        meaningful.append(stop)
                elif road and road.startswith(("N", "R")) and stop["duration"] >= 15:
                    # Major road with long stop - likely viewpoint/rest stop
                    stop["geo"] = geo
                    stop["meaningful_name"] = road
                    stop["type"] = "route"
                    meaningful.append(stop)
                else:
                    # Skip - no meaningful POI
                    logger.debug(f"Skipping stop at {stop['lat']:.4f}, {stop['lon']:.4f} - no POI")

            except Exception as e:
                logger.debug(f"Failed to geocode stop: {e}")
                continue

        return meaningful

    def _format_stop(self, stop: dict) -> dict:
        """Format stop information for narrative."""
        geo = stop.get("geo", {})
        poi_name = geo.get("poi_name")
        road = geo.get("road")
        village = geo.get("village")
        town = geo.get("town")
        county = geo.get("county")

        if poi_name:
            # Named POI
            location_parts = [poi_name]
            if village or town:
                location_parts.append(village or town)
            description = ", ".join(location_parts)
            return {"type": "poi", "description": description}

        elif village or town:
            # Town/village stop
            description = village or town
            if county:
                description += f", {county}"
            return {"type": "poi", "description": description}

        elif road:
            # Road (viewpoint or rest area)
            description = road
            if county:
                description += f" in {county}"
            return {"type": "route", "description": description}

        else:
            return {"type": "unknown", "description": ""}

    def _calculate_distance(self, waypoints: list[Waypoint]) -> float:
        """Calculate total distance."""
        total = 0.0
        for i in range(len(waypoints) - 1):
            total += self._haversine(
                waypoints[i].latitude,
                waypoints[i].longitude,
                waypoints[i + 1].latitude,
                waypoints[i + 1].longitude,
            )
        return total

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in km."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * R * asin(sqrt(a))
