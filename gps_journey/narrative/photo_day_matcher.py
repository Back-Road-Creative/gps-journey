"""
Enhanced Photo Matcher with Day-Based Organization and GPS Verification

Matches photos to specific journey days based on timestamps and GPS proximity.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

logger = logging.getLogger(__name__)

# Canonical day-proximity threshold (km): an item — a photo's GPS point, or a
# geocoded video endpoint — belongs to a journey day when it lands within this
# many km of one of that day's GPX trackpoints. Single-sourced here (this package
# owns the geo/day math) so other tools that match items to journey days can
# import it instead of hardcoding their own copy and drifting.
DEFAULT_GPS_PROXIMITY_KM: float = 5.0


class PhotoDayMatcher:
    """Match photos to journey days with GPS verification."""

    def __init__(
        self,
        time_tolerance_minutes: int = 5,
        gps_proximity_km: float = DEFAULT_GPS_PROXIMITY_KM,
    ):
        """
        Initialize photo day matcher.

        Args:
            time_tolerance_minutes: Time window for matching (±N minutes)
            gps_proximity_km: Maximum distance from route to consider valid (km)
        """
        self.time_tolerance = timedelta(minutes=time_tolerance_minutes)
        self.gps_proximity_km = gps_proximity_km

    def match_photos_to_days(
        self,
        journey_days: list[dict],
        photos: list[dict],
    ) -> dict[int, list[dict]]:
        """
        Match photos to specific journey days.

        Args:
            journey_days: List of day dictionaries with:
                - day_number: int
                - start_time: datetime
                - end_time: datetime
                - route: List of (lat, lon) tuples
            photos: List of photo dictionaries with:
                - filename: str
                - exif_datetime: Optional[datetime]
                - gps_coords: Optional[Tuple[float, float]]
                - other fields...

        Returns:
            Dictionary mapping day_number -> list of photos
        """
        day_photos = defaultdict(list)
        matched_count = 0
        unmatched_photos = []

        for photo in photos:
            photo_time = photo.get("exif_datetime")
            photo_coords = photo.get("gps_coords")

            if not photo_time:
                logger.warning(
                    f"Photo {photo.get('filename', 'unknown')} has no EXIF timestamp, skipping"
                )
                unmatched_photos.append(photo)
                continue

            # Find matching day by timestamp
            matched_day = None
            for day in journey_days:
                if day["start_time"] <= photo_time <= day["end_time"]:
                    # Verify GPS proximity if photo has coordinates
                    if photo_coords and day.get("route"):
                        if self._is_near_route(photo_coords, day["route"]):
                            matched_day = day["day_number"]
                            logger.debug(
                                f"Matched {photo.get('filename')} to day {matched_day} "
                                f"via timestamp + GPS"
                            )
                            break
                        else:
                            logger.warning(
                                f"Photo {photo.get('filename')} timestamp matches day "
                                f"{day['day_number']} but GPS coords "
                                f"{photo_coords} are far from route"
                            )
                    else:
                        # No GPS coords, trust timestamp
                        matched_day = day["day_number"]
                        logger.debug(
                            f"Matched {photo.get('filename')} to day {matched_day} "
                            f"via timestamp only"
                        )
                        break

            if matched_day is not None:
                day_photos[matched_day].append(photo)
                matched_count += 1
            else:
                unmatched_photos.append(photo)

        # Sort photos within each day by timestamp
        for day_num in day_photos:
            day_photos[day_num].sort(key=lambda p: p.get("exif_datetime") or datetime.min)

        logger.info(
            f"Matched {matched_count}/{len(photos)} photos to journey days. "
            f"{len(unmatched_photos)} unmatched."
        )

        return dict(day_photos)

    def _is_near_route(
        self, photo_coords: tuple[float, float], route: list[tuple[float, float]]
    ) -> bool:
        """
        Check if photo GPS is within proximity threshold of route.

        Args:
            photo_coords: (lat, lon) of photo
            route: List of (lat, lon) tuples representing the route

        Returns:
            True if photo is within gps_proximity_km of any route point
        """
        photo_lat, photo_lon = photo_coords

        for route_lat, route_lon in route:
            distance = self._haversine_distance(photo_lat, photo_lon, route_lat, route_lon)
            if distance <= self.gps_proximity_km:
                return True

        return False

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two GPS points in kilometers.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Distance in kilometers
        """
        R = 6371  # Earth radius in km

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))

        return R * c

    def generate_photo_captions(
        self, photos: list[dict], day_data: dict | None = None
    ) -> list[dict]:
        """
        Generate contextual captions for photos using geocoded locations.

        Args:
            photos: List of photo dictionaries
            day_data: Optional day data for additional context

        Returns:
            List of photos with enhanced captions
        """
        enhanced_photos = []

        for photo in photos:
            enhanced_photo = photo.copy()

            # Generate caption if missing
            if not enhanced_photo.get("caption"):
                caption = self._generate_caption(photo, day_data)
                enhanced_photo["caption"] = caption

            enhanced_photos.append(enhanced_photo)

        return enhanced_photos

    def _generate_caption(self, photo: dict, day_data: dict | None = None) -> str:
        """Generate a caption for a photo."""
        location = photo.get("geocoded_location")
        exif_time = photo.get("exif_datetime")

        parts = []

        if location:
            # Extract meaningful location parts
            if isinstance(location, dict):
                # If location is a dict, extract relevant fields
                town = location.get("town") or location.get("city")
                county = location.get("county")
                if town:
                    parts.append(town)
                if county and county != town:
                    parts.append(county)
            elif isinstance(location, str):
                parts.append(location)

        if exif_time and isinstance(exif_time, datetime):
            time_str = exif_time.strftime("%H:%M")
            if parts:
                caption = f"{', '.join(parts)} - {time_str}"
            else:
                caption = f"Journey photo at {time_str}"
        elif parts:
            caption = ", ".join(parts)
        else:
            caption = "Journey photo"

        return caption

    def get_day_photo_summary(self, day_photos: dict[int, list[dict]]) -> dict[int, dict]:
        """
        Get summary statistics for photos by day.

        Args:
            day_photos: Dictionary mapping day_number -> list of photos

        Returns:
            Dictionary with photo counts and time ranges per day
        """
        summary = {}

        for day_num, photos in day_photos.items():
            if not photos:
                continue

            # Get time range
            times = [p.get("exif_datetime") for p in photos if p.get("exif_datetime")]
            if times:
                first_photo = min(times)
                last_photo = max(times)
                time_range = (first_photo, last_photo)
            else:
                time_range = None

            summary[day_num] = {
                "photo_count": len(photos),
                "time_range": time_range,
                "first_photo_time": time_range[0] if time_range else None,
                "last_photo_time": time_range[1] if time_range else None,
            }

        return summary
