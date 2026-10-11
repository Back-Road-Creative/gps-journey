"""GPX file parsing using gpxpy library."""

import logging
from pathlib import Path

import gpxpy
import gpxpy.gpx

from gps_journey.core.models import Journey, JourneyStatistics, Waypoint

logger = logging.getLogger(__name__)


class GPXParser:
    """Parse GPX files and extract journey data."""

    def __init__(self, include_waypoints: bool = False) -> None:
        """
        Args:
            include_waypoints: When True, fold explicit ``<wpt>`` markers and
                route ``<rtept>`` points into the trace alongside track points.
                Defaults to False: operator-supplied external GPX routinely
                carries saved-favorite ``<wpt>`` markers far from the drive, and
                folding them pollutes county voting, chapters, endpoints, and
                stats. Timeless markers are dropped regardless of this flag.
        """
        self.include_waypoints = include_waypoints

    def parse(self, gpx_path: str | Path) -> Journey:
        """
        Parse GPX file and return Journey object.

        Args:
            gpx_path: Path to GPX file

        Returns:
            Journey object with waypoints and statistics

        Raises:
            FileNotFoundError: If GPX file doesn't exist
            ValueError: If GPX file is malformed or empty
        """
        gpx_path = Path(gpx_path)
        if not gpx_path.exists():
            raise FileNotFoundError(f"GPX file not found: {gpx_path}")

        logger.info(f"Parsing GPX file: {gpx_path}")

        with open(gpx_path, encoding="utf-8") as f:
            try:
                gpx = gpxpy.parse(f)
            except Exception as e:
                raise ValueError(f"Failed to parse GPX file: {e}") from e

        if not gpx.tracks and not gpx.waypoints and not gpx.routes:
            raise ValueError("GPX file contains no tracks, waypoints, or routes")

        # Extract waypoints from tracks and explicit waypoints
        waypoints = self._extract_waypoints(gpx)

        if not waypoints:
            raise ValueError("No valid waypoints found in GPX file")

        logger.info(f"Extracted {len(waypoints)} waypoints")

        # Calculate statistics
        statistics = self._calculate_statistics(gpx)

        # Determine start and end dates
        start_date = waypoints[0].timestamp
        end_date = waypoints[-1].timestamp

        return Journey(
            start_date=start_date,
            end_date=end_date,
            waypoints=tuple(waypoints),
            statistics=statistics,
        )

    def _extract_waypoints(self, gpx: gpxpy.gpx.GPX) -> list[Waypoint]:
        """Extract waypoints from GPX track points.

        Only ``<trkpt>`` track points are included by default — these form the
        authoritative trace. Explicit ``<wpt>`` markers and route ``<rtept>``
        points are folded in only when ``include_waypoints`` is set.

        A point without a timestamp is dropped rather than stamped with a naive
        ``datetime.now()``: a wall-clock fallback both fabricates the journey
        bounds and raises ``TypeError`` when sorted against tz-aware track points.
        """
        waypoints: list[Waypoint] = []

        # Track points (<trkpt>) — the authoritative trace (most common).
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if point.time:  # Only include points with timestamps
                        waypoints.append(
                            Waypoint(
                                latitude=point.latitude,
                                longitude=point.longitude,
                                timestamp=point.time,
                                elevation=point.elevation,
                                name=None,
                                description=None,
                            )
                        )

        if self.include_waypoints:
            # Explicit <wpt> markers (opt-in — may sit far from the drive).
            for wpt in gpx.waypoints:
                if wpt.time is None:  # Drop timeless markers, never fabricate now()
                    continue
                waypoints.append(
                    Waypoint(
                        latitude=wpt.latitude,
                        longitude=wpt.longitude,
                        timestamp=wpt.time,
                        elevation=wpt.elevation,
                        name=wpt.name,
                        description=wpt.description,
                    )
                )

            # Route points (<rtept>) (opt-in, less common).
            for route in gpx.routes:
                for point in route.points:
                    if point.time is None:  # Drop timeless points
                        continue
                    waypoints.append(
                        Waypoint(
                            latitude=point.latitude,
                            longitude=point.longitude,
                            timestamp=point.time,
                            elevation=point.elevation,
                            name=point.name,
                            description=point.description,
                        )
                    )

        # Sort by timestamp
        waypoints.sort(key=lambda w: w.timestamp)

        return waypoints

    def _calculate_statistics(self, gpx: gpxpy.gpx.GPX) -> JourneyStatistics | None:
        """Calculate journey statistics from GPX data."""
        if not gpx.tracks:
            return None

        try:
            # Use gpxpy's built-in calculation methods
            moving_data = gpx.get_moving_data()
            uphill_downhill = gpx.get_uphill_downhill()
            gpx.get_bounds()

            # Convert meters to kilometers and miles
            distance_km = gpx.length_3d() / 1000 if gpx.length_3d() else 0
            distance_miles = distance_km * 0.621371

            # Get elevation data
            uphill = uphill_downhill.uphill if uphill_downhill.uphill else 0
            downhill = uphill_downhill.downhill if uphill_downhill.downhill else 0

            # Get moving data
            moving_time = moving_data.moving_time if moving_data else 0
            stopped_time = moving_data.stopped_time if moving_data else 0

            # Calculate average speed (km/h)
            avg_speed_kmh = 0.0
            max_speed_kmh = 0.0
            if moving_data and moving_time > 0:
                # moving_data stores distance in meters
                avg_speed_kmh = (moving_data.moving_distance / 1000) / (moving_time / 3600)
                max_speed_kmh = moving_data.max_speed * 3.6 if moving_data.max_speed else 0

            # Get min/max elevation from tracks
            elevations = []
            for track in gpx.tracks:
                for segment in track.segments:
                    for point in segment.points:
                        if point.elevation is not None:
                            elevations.append(point.elevation)

            min_elevation = min(elevations) if elevations else 0
            max_elevation = max(elevations) if elevations else 0

            return JourneyStatistics(
                total_distance_km=distance_km,
                total_distance_miles=distance_miles,
                total_elevation_gain_m=uphill,
                total_elevation_loss_m=downhill,
                moving_time_seconds=moving_time,
                stopped_time_seconds=stopped_time,
                average_speed_kmh=avg_speed_kmh,
                max_speed_kmh=max_speed_kmh,
                min_elevation_m=min_elevation,
                max_elevation_m=max_elevation,
            )

        except Exception as e:
            logger.warning(f"Failed to calculate statistics: {e}")
            return None
