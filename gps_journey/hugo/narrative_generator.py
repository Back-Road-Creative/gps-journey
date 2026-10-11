"""Factual narrative generator from GPS data only - no creative writing or research."""

import logging
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt

from gps_journey.core.models import Journey, Waypoint, local_day, to_local
from gps_journey.geocoding.base import GeocodingProvider

logger = logging.getLogger(__name__)


class FactualNarrativeGenerator:
    """
    Generate factual, data-driven narratives from GPS tracks.

    RULES (per governance):
    - NO creative writing or embellishment
    - NO research or external knowledge
    - ONLY state facts from GPS data
    - Include: dates, times, coordinates, distances, elevations
    - Include: geocoded locations (towns/roads) if available
    - Include: detected stops (stationary periods)
    - NO assumptions about "why" or "feelings"
    """

    def __init__(self, geocoder: GeocodingProvider | None = None):
        """
        Initialize factual narrative generator.

        Args:
            geocoder: Optional geocoder for location names
        """
        self.geocoder = geocoder

    def generate_day_by_day(self, journey: Journey) -> str:
        """
        Generate day-by-day factual narrative from journey data.

        Args:
            journey: Journey with GPS waypoints

        Returns:
            Markdown formatted day-by-day narrative with only facts
        """
        lines = []
        lines.append("## Day-by-Day Route")
        lines.append("")
        lines.append("*GPS data only - no creative content or research*")
        lines.append("")

        # Group waypoints by day
        waypoints_by_day = self._group_by_day(journey.waypoints)

        for day_num, (date, waypoints) in enumerate(sorted(waypoints_by_day.items()), 1):
            lines.extend(self._format_day(day_num, date, waypoints))

        return "\n".join(lines)

    def _group_by_day(self, waypoints: tuple[Waypoint, ...]) -> dict:
        """Group waypoints by calendar day."""
        waypoints_by_day = defaultdict(list)
        for waypoint in waypoints:
            # GPX times are UTC; bucket by longitude-local day (see to_local)
            day_key = local_day(waypoint.timestamp, waypoint.longitude)
            waypoints_by_day[day_key].append(waypoint)
        return waypoints_by_day

    def _format_day(self, day_num: int, date, waypoints: list[Waypoint]) -> list[str]:
        """Format a single day's data as factual narrative."""
        lines = []

        first = waypoints[0]
        last = waypoints[-1]
        duration_hours = (last.timestamp - first.timestamp).total_seconds() / 3600

        # Day header
        lines.append(f"### Day {day_num}: {date.strftime('%A, %B %d, %Y')}")
        lines.append("")

        # Departure (times are local, derived from longitude)
        lines.append(
            f"**Departed:** {to_local(first.timestamp, first.longitude).strftime('%I:%M %p')}"
        )
        if first.location:
            lines.append(f"**From:** {first.location}")
        else:
            lines.append(f"**From:** {first.latitude:.4f}°, {first.longitude:.4f}°")

        if first.elevation:
            lines.append(f"**Starting elevation:** {first.elevation:.0f} m")

        lines.append("")

        # Route stats
        distance_km = self._calculate_distance(waypoints)
        elevation_gain, elevation_loss = self._calculate_elevation_change(waypoints)

        lines.append("**Route Statistics:**")
        lines.append(f"- Distance: {distance_km:.1f} km")
        lines.append(f"- Duration: {duration_hours:.1f} hours")
        lines.append(f"- Waypoints: {len(waypoints):,}")

        if elevation_gain > 0:
            lines.append(f"- Elevation gain: {elevation_gain:.0f} m")
            lines.append(f"- Elevation loss: {elevation_loss:.0f} m")

        lines.append("")

        # Detect stops (simplified - would need more logic for real stops)
        stops = self._detect_stops(waypoints)
        if stops:
            lines.append("**Detected Stops:**")
            for i, stop in enumerate(stops[:5], 1):  # Max 5 stops per day
                location_str = (
                    str(stop["location"])
                    if stop["location"]
                    else f"{stop['lat']:.4f}°, {stop['lon']:.4f}°"
                )
                lines.append(
                    f"{i}. {to_local(stop['time'], stop['lon']).strftime('%I:%M %p')} - "
                    f"{stop['duration']} minutes at {location_str}"
                )
            if len(stops) > 5:
                lines.append(f"   *(+{len(stops) - 5} more stops)*")
            lines.append("")

        # Arrival (times are local, derived from longitude)
        lines.append(
            f"**Arrived:** {to_local(last.timestamp, last.longitude).strftime('%I:%M %p')}"
        )
        if last.location:
            lines.append(f"**At:** {last.location}")
        else:
            lines.append(f"**At:** {last.latitude:.4f}°, {last.longitude:.4f}°")

        if last.elevation:
            lines.append(f"**Ending elevation:** {last.elevation:.0f} m")

        lines.append("")
        lines.append("---")
        lines.append("")

        return lines

    def _calculate_distance(self, waypoints: list[Waypoint]) -> float:
        """Calculate distance using Haversine formula."""

        def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            R = 6371  # Earth radius in km
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            return 2 * R * asin(sqrt(a))

        total_distance = 0.0
        for i in range(len(waypoints) - 1):
            w1, w2 = waypoints[i], waypoints[i + 1]
            total_distance += haversine(w1.latitude, w1.longitude, w2.latitude, w2.longitude)

        return total_distance

    def _calculate_elevation_change(self, waypoints: list[Waypoint]) -> tuple[float, float]:
        """Calculate total elevation gain and loss."""
        gain = 0.0
        loss = 0.0

        for i in range(len(waypoints) - 1):
            if waypoints[i].elevation and waypoints[i + 1].elevation:
                diff = waypoints[i + 1].elevation - waypoints[i].elevation
                if diff > 0:
                    gain += diff
                else:
                    loss += abs(diff)

        return gain, loss

    def _detect_stops(self, waypoints: list[Waypoint]) -> list[dict]:
        """
        Detect stops where vehicle was stationary.

        Simple heuristic: same coordinates for >5 minutes.
        Real implementation would use speed and position clustering.
        """
        stops = []
        stop_threshold_minutes = 5
        position_threshold_km = 0.05  # 50 meters

        i = 0
        while i < len(waypoints) - 1:
            current = waypoints[i]
            j = i + 1

            # Look ahead for same position
            while j < len(waypoints):
                distance = self._haversine_single(
                    current.latitude,
                    current.longitude,
                    waypoints[j].latitude,
                    waypoints[j].longitude,
                )

                if distance > position_threshold_km:
                    break
                j += 1

            # Check if stopped long enough
            if j > i + 1:
                duration_seconds = (waypoints[j - 1].timestamp - current.timestamp).total_seconds()
                duration_minutes = int(duration_seconds / 60)

                if duration_minutes >= stop_threshold_minutes:
                    stops.append(
                        {
                            "time": current.timestamp,
                            "duration": duration_minutes,
                            "lat": current.latitude,
                            "lon": current.longitude,
                            "location": current.location,
                        }
                    )

            i = j if j > i + 1 else i + 1

        return stops

    def _haversine_single(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * R * asin(sqrt(a))
