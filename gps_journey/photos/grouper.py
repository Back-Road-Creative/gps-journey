"""Photo grouping by geographic location."""

import math
from datetime import timedelta

from gps_journey.core.models import Photo, PhotoGroup

# Sentinel for photo groups that have no GPS fix (0.0/0.0 coords). It marks
# "location not yet known" internally; the Hugo publish gate
# (HugoGenerator._normalize_location_name) neutralizes it so this placeholder
# never ships to the public site as if it were a real place.
UNKNOWN_LOCATION = "Unknown Location"


class PhotoLocationGrouper:
    """Group photos by location proximity."""

    # Time threshold for grouping non-GPS photos (30 minutes)
    NON_GPS_TIME_THRESHOLD = timedelta(minutes=30)

    def __init__(self, proximity_km: float = 0.5):
        """
        Initialize photo grouper.

        Args:
            proximity_km: Distance threshold for grouping (default 0.5km)
        """
        self.proximity_km = proximity_km

    def group_photos(self, photos: list[Photo]) -> list[PhotoGroup]:
        """
        Group photos by GPS proximity and assign location names.

        Algorithm:
        1. Separate photos with and without GPS coordinates
        2. Cluster GPS photos by proximity
        3. Cluster non-GPS photos by time proximity
        4. Merge all groups and sort chronologically
        5. Assign location names

        IMPORTANT: All photos with timestamps are included - non-GPS photos
        are grouped under "Unknown Location" but still appear in output.

        Args:
            photos: List of photos to group

        Returns:
            List of PhotoGroup sorted chronologically
        """
        if not photos:
            return []

        # Separate GPS and non-GPS photos
        gps_photos = [p for p in photos if p.has_gps()]
        non_gps_photos = [p for p in photos if not p.has_gps()]

        # Group GPS photos by location proximity
        gps_groups = self._group_by_location(gps_photos)

        # Group non-GPS photos by time proximity
        non_gps_groups = self._group_by_time(non_gps_photos)

        # Merge all groups
        all_groups = gps_groups + non_gps_groups

        # Sort groups chronologically by first photo timestamp
        all_groups.sort(key=lambda g: g.photos[0].timestamp)

        return all_groups

    def _group_by_location(self, photos: list[Photo]) -> list[PhotoGroup]:
        """Group GPS photos by geographic proximity."""
        if not photos:
            return []

        # Sort photos by timestamp for chronological processing
        sorted_photos = sorted(photos, key=lambda p: p.timestamp)

        # Cluster photos by proximity
        groups: list[list[Photo]] = []
        current_group: list[Photo] = []

        for photo in sorted_photos:
            if not current_group:
                # Start first group
                current_group.append(photo)
            else:
                # Check if photo belongs to current group
                # Compare with first photo in current group
                first_photo = current_group[0]
                distance_km = self._haversine_distance(
                    first_photo.latitude,
                    first_photo.longitude,
                    photo.latitude,
                    photo.longitude,
                )

                if distance_km <= self.proximity_km:
                    # Add to current group
                    current_group.append(photo)
                else:
                    # Start new group
                    groups.append(current_group)
                    current_group = [photo]

        # Add final group
        if current_group:
            groups.append(current_group)

        # Convert to PhotoGroup objects
        photo_groups = []
        for group in groups:
            # Use first photo's location for group metadata
            first_photo = group[0]
            location_name = self._get_location_name(first_photo)

            photo_group = PhotoGroup(
                location_name=location_name,
                latitude=first_photo.latitude,
                longitude=first_photo.longitude,
                photos=tuple(group),  # Photos already sorted chronologically
            )
            photo_groups.append(photo_group)

        return photo_groups

    def _group_by_time(self, photos: list[Photo]) -> list[PhotoGroup]:
        """
        Group non-GPS photos by time proximity.

        Photos within 30 minutes of each other are grouped together.
        This handles indoor shots, camera without GPS, etc.
        """
        if not photos:
            return []

        # Sort by timestamp
        sorted_photos = sorted(photos, key=lambda p: p.timestamp)

        # Cluster by time proximity
        groups: list[list[Photo]] = []
        current_group: list[Photo] = []

        for photo in sorted_photos:
            if not current_group:
                current_group.append(photo)
            else:
                # Check time difference from first photo in group
                first_photo = current_group[0]
                time_diff = photo.timestamp - first_photo.timestamp

                if time_diff <= self.NON_GPS_TIME_THRESHOLD:
                    current_group.append(photo)
                else:
                    # Start new group
                    groups.append(current_group)
                    current_group = [photo]

        # Add final group
        if current_group:
            groups.append(current_group)

        # Convert to PhotoGroup objects
        photo_groups = []
        for group in groups:
            photo_group = PhotoGroup(
                location_name=UNKNOWN_LOCATION,
                latitude=0.0,  # No GPS coordinates available
                longitude=0.0,
                photos=tuple(group),
            )
            photo_groups.append(photo_group)

        return photo_groups

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two GPS coordinates using Haversine formula.

        Args:
            lat1, lon1: First coordinate
            lat2, lon2: Second coordinate

        Returns:
            Distance in kilometers
        """
        # Earth radius in kilometers
        R = 6371.0

        # Convert to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Differences
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        # Haversine formula
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _get_location_name(self, photo: Photo) -> str:
        """
        Get location name from photo's location metadata.

        Builds name from available location components.

        Args:
            photo: Photo with location metadata

        Returns:
            Human-readable location name
        """
        if not photo.location:
            return f"{photo.latitude:.4f}, {photo.longitude:.4f}"

        # Build name from available components
        parts = []
        if photo.location.name:
            parts.append(photo.location.name)
        if photo.location.locality:
            parts.append(photo.location.locality)
        if photo.location.county:
            parts.append(photo.location.county)

        if parts:
            return ", ".join(parts)

        # Fallback to coordinates
        return f"{photo.latitude:.4f}, {photo.longitude:.4f}"
