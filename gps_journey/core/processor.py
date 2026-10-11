"""Journey processing orchestration."""

import logging
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

from gps_journey.core.gpx_parser import GPXParser
from gps_journey.core.models import (
    DayBreakdown,
    DayStatistics,
    Journey,
    Photo,
    Waypoint,
    local_day,
)
from gps_journey.geocoding.base import GeocodingError, GeocodingProvider
from gps_journey.geocoding.cache import GeocodingCache
from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient

logger = logging.getLogger(__name__)


class JourneyProcessor:
    """
    Orchestrate the complete journey processing pipeline.

    Coordinates GPX parsing, geocoding, photo matching, and content generation.
    """

    def __init__(
        self,
        geocoding_enabled: bool = False,
        photos_enabled: bool = False,
        geocoding_provider: GeocodingProvider | None = None,
        geocoding_cache_path: Path | None = None,
    ):
        """
        Initialize the journey processor.

        Args:
            geocoding_enabled: Enable geocoding of locations
            photos_enabled: Enable Google Photos integration
            geocoding_provider: Custom geocoding provider (default: Nominatim)
            geocoding_cache_path: Path to geocoding cache file
        """
        self.geocoding_enabled = geocoding_enabled
        self.photos_enabled = photos_enabled
        self.gpx_parser = GPXParser()

        # Initialize geocoding if enabled
        self.geocoder: GeocodingProvider | None = None
        if geocoding_enabled:
            if geocoding_provider:
                self.geocoder = geocoding_provider
            else:
                # Default to NominatimRoadsClient with TDD-tested location hierarchy
                cache = None
                if geocoding_cache_path:
                    cache = GeocodingCache(geocoding_cache_path)
                self.geocoder = NominatimRoadsClient(cache=cache)

    def process(self, gpx_path: str | Path) -> Journey:
        """
        Process a GPX file through the complete pipeline.

        Args:
            gpx_path: Path to GPX file

        Returns:
            Processed Journey object

        Raises:
            ValueError: If processing fails
        """
        logger.info(f"Starting journey processing for: {gpx_path}")

        # Phase 1: Parse GPX
        journey = self.gpx_parser.parse(gpx_path)
        logger.info(f"Parsed {len(journey.waypoints)} waypoints")

        # Phase 2: Geocoding (if enabled)
        if self.geocoding_enabled:
            journey = self._geocode_journey(journey)

        # Phase 3: Photo integration (if enabled)
        if self.photos_enabled:
            journey = self._integrate_photos(journey)

        logger.info("Journey processing complete")
        return journey

    def _geocode_journey(self, journey: Journey) -> Journey:
        """
        Geocode key locations in the journey.

        Geocodes:
        - Start location (first waypoint)
        - End location (last waypoint)
        - Explicit waypoints with names

        Args:
            journey: Journey to geocode

        Returns:
            Journey with geocoded locations
        """
        if not self.geocoder:
            logger.warning("Geocoding requested but no geocoder configured")
            return journey

        logger.info("Geocoding journey locations...")

        geocoded_waypoints = list(journey.waypoints)
        geocode_count = 0
        error_count = 0

        # Geocode start location
        if geocoded_waypoints:
            first = geocoded_waypoints[0]
            try:
                location = self.geocoder.reverse_geocode(first.latitude, first.longitude)
                geocoded_waypoints[0] = Waypoint(
                    latitude=first.latitude,
                    longitude=first.longitude,
                    timestamp=first.timestamp,
                    elevation=first.elevation,
                    name=first.name,
                    description=first.description,
                    location=location,
                )
                geocode_count += 1
                logger.info(f"Start: {location}")
            except GeocodingError as e:
                logger.warning(f"Failed to geocode start location: {e}")
                error_count += 1

        # Geocode end location
        if len(geocoded_waypoints) > 1:
            last = geocoded_waypoints[-1]
            try:
                location = self.geocoder.reverse_geocode(last.latitude, last.longitude)
                geocoded_waypoints[-1] = Waypoint(
                    latitude=last.latitude,
                    longitude=last.longitude,
                    timestamp=last.timestamp,
                    elevation=last.elevation,
                    name=last.name,
                    description=last.description,
                    location=location,
                )
                geocode_count += 1
                logger.info(f"End: {location}")
            except GeocodingError as e:
                logger.warning(f"Failed to geocode end location: {e}")
                error_count += 1

        logger.info(f"Geocoded {geocode_count} locations ({error_count} errors)")

        # Update journey with geocoded waypoints
        journey = journey.with_waypoints(geocoded_waypoints)

        # Set start/end locations
        if geocoded_waypoints:
            start_loc = geocoded_waypoints[0].location
            end_loc = geocoded_waypoints[-1].location
            if start_loc and end_loc:
                journey = journey.with_locations(start_loc, end_loc)

        return journey

    def _integrate_photos(self, journey: Journey) -> Journey:
        """Integrate photos from Google Photos (stub for Phase 2)."""
        logger.info("Photo integration not yet implemented")
        return journey

    def generate_daily_breakdowns(
        self, journey: Journey, photos_dir: Path | None = None
    ) -> Journey:
        """
        Generate daily breakdowns from journey waypoints and photos.

        Groups waypoints by calendar day (UTC), calculates daily statistics,
        matches photos to days, and generates auto-summary narratives.

        Args:
            journey: Journey with waypoints and optional photos
            photos_dir: Optional directory containing photos to load and match

        Returns:
            Journey with populated daily_breakdowns tuple
        """
        if not journey.waypoints:
            logger.warning("Cannot generate daily breakdowns: no waypoints")
            return journey

        logger.info("Generating daily breakdowns...")

        # Load photos from filesystem if directory provided
        if photos_dir:
            from gps_journey.photos.filesystem_loader import FilesystemPhotoLoader

            loader = FilesystemPhotoLoader()
            photos = loader.load_photos_from_directory(Path(photos_dir))
            if photos:
                journey = journey.with_photos(photos)
                logger.info(f"Loaded {len(photos)} photos from {photos_dir}")

        # Group waypoints by calendar day
        days_waypoints = self._group_waypoints_by_day(journey.waypoints)

        # Group photos by calendar day
        days_photos = self._group_photos_by_day(journey.photos)

        # Get sorted waypoint dates
        waypoint_dates = sorted(days_waypoints.keys())
        first_waypoint_date = waypoint_dates[0] if waypoint_dates else None
        last_waypoint_date = waypoint_dates[-1] if waypoint_dates else None

        # Distribute photos to matching waypoint days
        # - Photos before first day -> add to first day
        # - Photos after last day -> add to last day
        # - Photos on "gap days" (within range but no GPS) -> add to nearest day with GPS
        if days_photos and first_waypoint_date and last_waypoint_date:
            redistributed_photos: dict[date, list[Photo]] = defaultdict(list)
            waypoint_dates_set = set(waypoint_dates)

            for photo_date, photos_list in days_photos.items():
                if photo_date < first_waypoint_date:
                    # Pre-trip photos go to first day
                    redistributed_photos[first_waypoint_date].extend(photos_list)
                    logger.debug(
                        f"Moving {len(photos_list)} photos from {photo_date} to first day {first_waypoint_date}"
                    )
                elif photo_date > last_waypoint_date:
                    # Post-trip photos go to last day
                    redistributed_photos[last_waypoint_date].extend(photos_list)
                    logger.debug(
                        f"Moving {len(photos_list)} photos from {photo_date} to last day {last_waypoint_date}"
                    )
                elif photo_date not in waypoint_dates_set:
                    # Gap day - find nearest waypoint day
                    nearest_day = self._find_nearest_waypoint_day(photo_date, waypoint_dates)
                    redistributed_photos[nearest_day].extend(photos_list)
                    logger.debug(
                        f"Moving {len(photos_list)} photos from gap day {photo_date} to {nearest_day}"
                    )
                else:
                    # Photos match a waypoint day - keep on their day
                    redistributed_photos[photo_date].extend(photos_list)

            days_photos = dict(redistributed_photos)

        # Build daily breakdowns
        breakdowns = []
        for day_number, (day_date, waypoints) in enumerate(sorted(days_waypoints.items()), start=1):
            # Get photos for this day (now includes redistributed photos)
            day_photos = days_photos.get(day_date, [])
            # Sort photos by timestamp to maintain chronological order
            day_photos = sorted(day_photos, key=lambda p: p.timestamp)

            # Calculate statistics
            stats = self._calculate_day_statistics(
                day_number=day_number,
                day_date=day_date,
                waypoints=waypoints,
                photos=day_photos,
            )

            # Extract locations visited first (for narrative generation)
            locations_visited = self._extract_locations_visited(waypoints)

            # Generate narrative with location context
            narrative = self._generate_day_narrative(
                stats, waypoints, towns_visited=locations_visited
            )

            # Group photos by location if photos available
            photo_groups = ()
            if day_photos:
                from gps_journey.photos.grouper import PhotoLocationGrouper

                grouper = PhotoLocationGrouper(proximity_km=0.5)
                photo_groups_raw = grouper.group_photos(day_photos)

                # Geocode photo group locations if geocoder available
                geocoded_groups = []
                for group in photo_groups_raw:
                    location_name = group.location_name  # Default (coordinates)

                    if self.geocoder and group.latitude and group.longitude:
                        try:
                            location = self.geocoder.reverse_geocode(
                                group.latitude, group.longitude
                            )
                            if location:
                                # Use specific location name
                                location_name = (
                                    location.name
                                    or location.locality
                                    or location.city
                                    or f"{group.latitude:.4f}, {group.longitude:.4f}"
                                )
                        except Exception as e:
                            logger.debug(f"Failed to geocode photo location: {e}")

                    # Update group with geocoded name
                    from dataclasses import replace

                    geocoded_group = replace(group, location_name=location_name)
                    geocoded_groups.append(geocoded_group)

                photo_groups = tuple(geocoded_groups)

            # Create breakdown
            breakdown = DayBreakdown(
                statistics=stats,
                waypoints=tuple(waypoints),
                photos=tuple(day_photos),
                photo_groups=photo_groups,
                locations_visited=tuple(locations_visited),
                narrative=narrative,
                map_file=None,  # Will be set by map generation
                gpx_file=None,  # Will be set by GPX export
            )
            breakdowns.append(breakdown)

        logger.info(f"Generated {len(breakdowns)} daily breakdowns")

        # Return journey with daily_breakdowns using dataclass replace
        from dataclasses import replace

        return replace(journey, daily_breakdowns=tuple(breakdowns))

    def _group_waypoints_by_day(
        self, waypoints: tuple[Waypoint, ...]
    ) -> dict[date, list[Waypoint]]:
        """Group waypoints by longitude-local calendar day.

        GPX timestamps are UTC; bucketing by the raw UTC date would file a US
        evening drive under the wrong calendar day (and split drives crossing
        UTC midnight). ``local_day`` derives the day from each point's own
        longitude so the day header matches where the drive actually happened.
        """
        days = defaultdict(list)
        for waypoint in waypoints:
            day_date = local_day(waypoint.timestamp, waypoint.longitude)
            days[day_date].append(waypoint)
        return dict(days)

    def _group_photos_by_day(self, photos: tuple[Photo, ...]) -> dict[date, list[Photo]]:
        """Group photos by calendar day (based on timestamp date)."""
        days = defaultdict(list)
        for photo in photos:
            day_date = photo.timestamp.date()
            days[day_date].append(photo)
        return dict(days)

    def _calculate_day_statistics(
        self,
        day_number: int,
        day_date: date,
        waypoints: list[Waypoint],
        photos: list[Photo],
    ) -> DayStatistics:
        """Calculate statistics for a single day."""
        if not waypoints:
            raise ValueError("Cannot calculate statistics for day with no waypoints")

        # Start and end times
        start_time = waypoints[0].timestamp
        end_time = waypoints[-1].timestamp

        # Duration in hours
        duration_seconds = (end_time - start_time).total_seconds()
        duration_hours = duration_seconds / 3600.0

        # Calculate distance (simple haversine between consecutive points)
        total_distance_km = 0.0
        for i in range(len(waypoints) - 1):
            total_distance_km += self._haversine_distance(
                waypoints[i].latitude,
                waypoints[i].longitude,
                waypoints[i + 1].latitude,
                waypoints[i + 1].longitude,
            )

        # Calculate elevation gain and loss
        elevation_gain_m = 0.0
        elevation_loss_m = 0.0
        for i in range(len(waypoints) - 1):
            if waypoints[i].elevation is not None and waypoints[i + 1].elevation is not None:
                elevation_diff = waypoints[i + 1].elevation - waypoints[i].elevation
                if elevation_diff > 0:
                    elevation_gain_m += elevation_diff
                else:
                    elevation_loss_m += abs(elevation_diff)

        # Start and end locations (if geocoded)
        start_location = waypoints[0].location
        end_location = waypoints[-1].location

        return DayStatistics(
            day_number=day_number,
            date=day_date,
            distance_km=total_distance_km,
            duration_hours=duration_hours,
            elevation_gain_m=elevation_gain_m,
            elevation_loss_m=elevation_loss_m,
            photo_count=len(photos),
            waypoint_count=len(waypoints),
            start_time=start_time,
            end_time=end_time,
            start_location=start_location,
            end_location=end_location,
        )

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

    def _extract_locations_visited(self, waypoints: list[Waypoint]) -> list[str]:
        """
        Extract ALL location names visited during the day in chronological order.

        Samples waypoints and extracts location name from each, without
        duration filtering. This ensures even quick pass-throughs are captured.

        Uses TDD-tested location hierarchy: village > locality > city_district > city

        Args:
            waypoints: List of waypoints for the day

        Returns:
            List of all location names in chronological order (duplicates removed)
        """
        if not waypoints or not self.geocoder:
            return []

        # Sample waypoints (every 100th to avoid excessive API calls)
        sample_interval = 100
        locations = []
        seen_locations = set()

        logger.debug(
            f"Extracting locations from {len(waypoints)} waypoints (sampling every {sample_interval})"
        )

        for i in range(0, len(waypoints), sample_interval):
            wp = waypoints[i]
            try:
                # Geocode this waypoint
                location = self.geocoder.reverse_geocode(wp.latitude, wp.longitude)

                if location and location.name:
                    # Extract specific location name (TDD-tested hierarchy already applied)
                    loc_name = location.name

                    # Clean up duplicates while preserving chronological order
                    if loc_name and loc_name not in seen_locations:  # noqa: SIM102
                        # Skip if it's ONLY a county name (too generic)
                        if not (loc_name.startswith("County ") and ", " not in loc_name):
                            locations.append(loc_name)
                            seen_locations.add(loc_name)
                            logger.debug(f"Location {len(locations)}: {loc_name}")

            except Exception as e:
                logger.debug(f"Failed to geocode waypoint {i}: {e}")
                continue

        logger.info(f"Extracted {len(locations)} unique locations from {len(waypoints)} waypoints")

        # Ensure we have at least start and end locations as fallback
        if len(locations) < 2 and len(waypoints) >= 2:
            # Try geocoding first and last waypoint explicitly
            try:
                first_loc = self.geocoder.reverse_geocode(
                    waypoints[0].latitude, waypoints[0].longitude
                )
                last_loc = self.geocoder.reverse_geocode(
                    waypoints[-1].latitude, waypoints[-1].longitude
                )

                if first_loc and first_loc.name and first_loc.name not in seen_locations:
                    locations.insert(0, first_loc.name)
                if last_loc and last_loc.name and last_loc.name not in seen_locations:
                    locations.append(last_loc.name)

            except Exception as e:
                logger.warning(f"Failed to geocode start/end for fallback: {e}")

        return locations

    def _generate_day_narrative(
        self,
        stats: DayStatistics,
        waypoints: list[Waypoint],
        towns_visited: list[str] | None = None,
    ) -> str:
        """
        Generate descriptive narrative for a day using GPS data.

        Uses SimpleNarrativeGenerator to create quality prose.

        Args:
            stats: Day statistics
            waypoints: Waypoints for the day
            towns_visited: Optional list of towns passed through

        Returns:
            Descriptive narrative string
        """
        from gps_journey.narrative.simple_generator import SimpleNarrativeGenerator

        generator = SimpleNarrativeGenerator()

        # Extract location names
        start_name = ""
        end_name = ""
        if stats.start_location:
            start_name = (
                stats.start_location.name
                or stats.start_location.locality
                or stats.start_location.city
                or ""
            )
        if stats.end_location:
            end_name = (
                stats.end_location.name
                or stats.end_location.locality
                or stats.end_location.city
                or ""
            )

        return generator.generate_day_narrative(
            day_number=stats.day_number,
            date=stats.start_time,
            start_location=start_name,
            end_location=end_name,
            distance_km=stats.distance_km,
            duration_hours=stats.duration_hours,
            elevation_gain_m=stats.elevation_gain_m,
            towns_visited=towns_visited or [],
            photo_count=stats.photo_count,
        )

    def _find_nearest_waypoint_day(self, photo_date: date, waypoint_dates: list[date]) -> date:
        """
        Find the nearest waypoint day to a given photo date.

        Args:
            photo_date: Date of the photo
            waypoint_dates: Sorted list of dates with waypoints

        Returns:
            The nearest date with waypoints
        """
        # Find the closest date (preferring earlier dates in case of tie)
        closest_date = waypoint_dates[0]
        min_distance = abs((photo_date - closest_date).days)

        for wp_date in waypoint_dates:
            distance = abs((photo_date - wp_date).days)
            if distance < min_distance:
                min_distance = distance
                closest_date = wp_date

        return closest_date
