"""Rich narrative generator using GPS data - no external API needed."""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# Location name patterns to filter out
BAD_LOCATION_PATTERNS = [
    # Coordinate-only patterns (no real place name found)
    r"^\d+\.\d+[°]?,\s*-?\d+\.\d+[°]?$",  # e.g., "0.0000°, 0.0000°"
    r"^-?\d+\.\d+,\s*-?\d+\.\d+$",  # e.g., "51.2500, -7.4250"
    r"^0\.0+[°]?,\s*0\.0+[°]?$",  # Zero coordinates specifically
    # Administrative codes (Irish electoral divisions)
    r"No\.\s*\d+\s*Urban",
    r"No\.\s*\d+\s*Rural",
    r"^.*Urban,\s*County",
    r"^.*Rural,\s*County",
    r"DED\b",
    r"Electoral\b",
    # Parking locations
    r"Car\s*Park",
    r"\bParking\b",
    r"^P\d+\b",
    # Commercial/generic POIs (not meaningful destinations)
    r"^(Tesco|Lidl|Aldi|SuperValu|Dunnes|Centra|Spar|Maxol|Circle K|BP|Shell|Applegreen)\b",
    # Road/infrastructure
    r"^(Roundabout|Junction|Interchange|Exit\s+\d+)\b",
    r"^(N\d+|M\d+|R\d+|L\d+)\s*$",  # Road numbers only
    # Unincorporated/unnamed areas (but allow "Unincorporated X" as valid)
    r"^Unincorporated$",  # Only filter if it's JUST "Unincorporated" alone
    # Redundant place names (e.g., "Town, Town" or "Place, Place")
    r"^([^,]+),\s*\1$",  # Matches "X, X" pattern
]

# Compiled patterns for efficiency
_BAD_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BAD_LOCATION_PATTERNS]


def filter_locations(locations: list[str]) -> list[str]:
    """Filter out bad location names (admin codes, parking, commercial POIs).

    Args:
        locations: List of location names

    Returns:
        Filtered list with meaningful location names only
    """
    filtered = []
    for loc in locations:
        if not loc or not loc.strip():
            continue

        # Check against bad patterns
        is_bad = any(p.search(loc) for p in _BAD_PATTERNS)
        if not is_bad:
            filtered.append(loc)

    return filtered


class SimpleNarrativeGenerator:
    """Generate publication-quality narratives from GPS data."""

    def generate_day_narrative(
        self,
        day_number: int,
        date: datetime,
        start_location: str,
        end_location: str,
        distance_km: float,
        duration_hours: float,
        elevation_gain_m: float,
        towns_visited: list[str],
        photo_count: int,
    ) -> str:
        """
        Generate a rich, descriptive narrative for a day's journey.

        Creates engaging prose that describes the route, terrain, and
        photography activity using actual GPS data.

        Args:
            day_number: Day number
            date: Date of travel
            start_location: Starting location name
            end_location: Ending location name
            distance_km: Distance traveled (0 for photo-only journeys)
            duration_hours: Duration in hours
            elevation_gain_m: Elevation gain
            towns_visited: List of towns passed through
            photo_count: Number of photos taken

        Returns:
            Descriptive narrative (100-250 words)
        """
        # Filter towns to remove bad location names
        towns_visited = filter_locations(towns_visited)

        # Filter start/end locations too
        start_filtered = filter_locations([start_location]) if start_location else []
        end_filtered = filter_locations([end_location]) if end_location else []
        start_location = start_filtered[0] if start_filtered else ""
        end_location = end_filtered[0] if end_filtered else ""

        # Build engaging opening - handle photo-only journeys (distance=0)
        is_photo_journey = distance_km < 1.0  # Less than 1km = photo-only

        if is_photo_journey:
            # Photo-based journey - don't mention distance
            if start_location and end_location:
                if start_location == end_location:
                    opening = f"Exploring the {start_location} area"
                else:
                    opening = f"Traveling from {start_location} to {end_location}"
            else:
                opening = f"Day {day_number} of the journey"
        else:
            # GPS-tracked journey - include distance
            distance_mi = distance_km * 0.621371
            distance_str = f"{distance_km:.0f} km ({distance_mi:.0f} miles)"

            if start_location and end_location:
                if start_location == end_location:
                    opening = f"Exploring the {start_location} area on a {distance_str} circuit"
                else:
                    opening = f"Traveling from {start_location} to {end_location}, covering {distance_str}"
            else:
                opening = f"Day {day_number} journey of {distance_str}"

        # Add route details with towns - list all meaningful ones
        # IMPORTANT: Filter out start/end locations to avoid redundancy
        # e.g., avoid "from X to Y through X, Y" which sounds silly
        start_normalized = start_location.lower().strip() if start_location else ""
        end_normalized = end_location.lower().strip() if end_location else ""

        intermediate_towns = []
        seen = set()
        for t in towns_visited:
            normalized = t.lower().strip()
            # Skip if it's the start or end location (avoid redundancy)
            if normalized in (start_normalized, end_normalized):
                continue
            if normalized not in seen:
                seen.add(normalized)
                intermediate_towns.append(t)

        if intermediate_towns:
            if len(intermediate_towns) <= 4:
                # List all intermediate locations
                towns_str = ", ".join(intermediate_towns)
                route_detail = f" through {towns_str}"
            else:
                # For longer lists, summarize
                first_towns = ", ".join(intermediate_towns[:3])
                route_detail = f" through {first_towns} and other locations"

            narrative = opening + route_detail
        else:
            narrative = opening

        # Add terrain description based on elevation (only for GPS journeys)
        if not is_photo_journey and elevation_gain_m > 0:
            if elevation_gain_m > 1500:
                narrative += f". The route featured significant climbing with {elevation_gain_m:.0f} meters of elevation gain"
            elif elevation_gain_m > 800:
                narrative += f". The journey included substantial elevation changes with {elevation_gain_m:.0f} meters of ascent"
            elif elevation_gain_m > 300:
                narrative += f" with {elevation_gain_m:.0f} meters of elevation gain"

        # Add photography context with varied phrasing
        if photo_count >= 20:
            # Use varied phrasing based on day number
            phrases = [
                f". {photo_count} photos captured throughout the day",
                f". The day yielded {photo_count} photographs",
                f". Documented with {photo_count} photos",
            ]
            narrative += phrases[day_number % len(phrases)]
        elif photo_count > 5:
            narrative += f". {photo_count} photos captured along the route"
        elif photo_count > 0:
            narrative += f" with {photo_count} photos"

        # Ensure proper ending
        if not narrative.endswith("."):
            narrative += "."

        return narrative

    def generate_journey_overview(
        self,
        title: str,
        start_date: datetime,
        end_date: datetime,
        start_location: str,
        end_location: str,
        total_distance_km: float,
        duration_days: int,
        total_photos: int,
    ) -> str:
        """
        Generate rich journey overview narrative.

        Creates engaging summary of the entire journey with geographic
        and photographic context.

        Returns:
            Overview description (50-150 words)
        """
        # Filter locations
        start_filtered = filter_locations([start_location]) if start_location else []
        end_filtered = filter_locations([end_location]) if end_location else []
        start_location = start_filtered[0] if start_filtered else ""
        end_location = end_filtered[0] if end_filtered else ""

        is_photo_journey = total_distance_km < 1.0

        if is_photo_journey:
            # Photo-based journey overview
            if start_location and end_location:
                if start_location == end_location:
                    overview = (
                        f"A {duration_days}-day exploration of the {start_location} region, "
                        f"documented through photography and travel experiences"
                    )
                else:
                    overview = (
                        f"A {duration_days}-day journey from {start_location} to {end_location}, "
                        f"captured through photographs of the landscapes and culture"
                    )
            else:
                overview = (
                    f"A {duration_days}-day photographic journey "
                    f"exploring diverse landscapes and memorable locations"
                )
        else:
            distance_mi = total_distance_km * 0.621371

            # GPS-tracked journey with distance
            if start_location and end_location:
                if start_location == end_location:
                    overview = (
                        f"An extensive {duration_days}-day exploration of the {start_location} region, "
                        f"covering {total_distance_km:.0f} km ({distance_mi:.0f} miles)"
                    )
                else:
                    overview = (
                        f"A {duration_days}-day road trip from {start_location} to {end_location}, "
                        f"spanning {total_distance_km:.0f} km ({distance_mi:.0f} miles) across "
                        f"varied terrain and cultural regions"
                    )
            else:
                overview = (
                    f"A comprehensive {duration_days}-day journey covering "
                    f"{total_distance_km:.0f} km ({distance_mi:.0f} miles) "
                    f"exploring diverse landscapes and routes"
                )

        # Add photography context
        if total_photos >= 100:
            overview += f". Extensively documented with {total_photos} photographs capturing landscapes, cultural landmarks, and memorable moments along the route"
        elif total_photos >= 20:
            overview += f". The journey was documented with {total_photos} photographs highlighting scenic viewpoints and notable locations"
        elif total_photos > 0:
            overview += f" with {total_photos} photos"

        # Ensure proper ending
        if not overview.endswith("."):
            overview += "."

        return overview
