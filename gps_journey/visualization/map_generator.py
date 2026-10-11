"""
Interactive Map Generation Module

Generates beautiful, interactive Leaflet.js maps from GPS journey data using Folium.
Maps include route polylines, photo markers, start/end points, and multiple tile layers.

The generated HTML maps:
- Load quickly (<2 seconds with simplified polylines)
- Work offline (all assets embedded)
- Are mobile-responsive
- Support zooming, panning, and layer switching
- Display photo locations with camera icons

Output: Standalone HTML files ready for Hugo embedding via mapembed shortcode
"""

import logging
from pathlib import Path

import folium
from folium import plugins

from gps_journey.core.models import Journey, to_local
from gps_journey.photos.models import MatchedPhoto
from gps_journey.visualization.a11y import accessible_html, title_for_slug
from gps_journey.visualization.simplify import calculate_reduction, simplify_polyline

logger = logging.getLogger(__name__)

# Type alias
Point = tuple[float, float]  # (latitude, longitude)


def _save_accessible(map_obj, output_path: Path) -> None:
    """Render the map to disk, then repair what Folium's template omits.

    Never call `map_obj.save()` directly. Folium writes every page with no
    `lang`, no `<title>` and pinch-zoom disabled -- three WCAG failures. This
    helper adds the language and a title and re-enables zoom. The title comes
    from the filename, so regenerating a journey does not rename it.
    """
    map_obj.save(str(output_path))
    output_path.write_text(
        accessible_html(output_path.read_text(encoding="utf-8"), title_for_slug(output_path.stem)),
        encoding="utf-8",
    )


class MapGenerator:
    """
    Generates interactive Folium/Leaflet maps from GPS journey data.

    Features:
    - Simplified polyline routes for fast loading
    - Start/end markers with popups
    - Photo location markers with camera icons
    - Multiple tile layers (street, terrain, satellite)
    - Auto-fitted bounds
    - Customizable styling via config

    Example:
        >>> from gps_journey.core.gpx_parser import GPXParser
        >>> journey = GPXParser().parse("trip.gpx")
        >>> generator = MapGenerator()
        >>> generator.generate_journey_map(
        ...     journey=journey,
        ...     output_path="static/maps/trip.html"
        ... )
    """

    def __init__(
        self,
        route_color: str = "#2563eb",  # blue-600
        route_weight: int = 3,
        route_opacity: float = 0.7,
        simplify_tolerance: float = 0.0001,  # ~11m at Ireland latitude
        min_points: int = 100,
    ):
        """
        Initialize map generator with styling options.

        Args:
            route_color: Hex color for route polyline (default: blue-600)
            route_weight: Line weight in pixels (default: 3)
            route_opacity: Line opacity 0-1 (default: 0.7)
            simplify_tolerance: Polyline simplification tolerance in degrees
            min_points: Minimum points to keep in simplified polyline
        """
        self.route_color = route_color
        self.route_weight = route_weight
        self.route_opacity = route_opacity
        self.simplify_tolerance = simplify_tolerance
        self.min_points = min_points

    def _calculate_center(self, points: list[Point]) -> Point:
        """
        Calculate the geographic center (mean) of a list of points.

        Args:
            points: List of (latitude, longitude) tuples

        Returns:
            Center point as (latitude, longitude)
        """
        if not points:
            # Default to Ireland center
            return (53.5, -8.0)

        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        return (sum(lats) / len(lats), sum(lons) / len(lons))

    def _calculate_bounds(self, points: list[Point]) -> list[list[float]]:
        """
        Calculate the bounding box for a list of points.

        Args:
            points: List of (latitude, longitude) tuples

        Returns:
            Bounds in format [[south, west], [north, east]] for Folium
        """
        if not points:
            # Default Ireland bounds
            return [[51.5, -10.5], [55.5, -5.5]]

        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        return [
            [min(lats), min(lons)],  # southwest
            [max(lats), max(lons)],  # northeast
        ]

    def _add_tile_layers(self, map_obj: folium.Map):
        """
        Add multiple tile layer options to the map.

        Layers:
        - OpenStreetMap (default): Detailed street map
        - OpenTopoMap: Topographic with contour lines
        - Esri World Imagery: Satellite view
        - CartoDB Positron: Minimalist light theme

        All layers are free and require no API keys.

        Args:
            map_obj: Folium map object to add layers to
        """
        # OpenTopoMap - topographic with elevation contours
        folium.TileLayer(
            tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            attr="Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap",
            name="Terrain",
            overlay=False,
            control=True,
        ).add_to(map_obj)

        # Esri World Imagery - satellite view
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Tiles © Esri",
            name="Satellite",
            overlay=False,
            control=True,
        ).add_to(map_obj)

        # CartoDB Positron - clean minimal style
        folium.TileLayer(
            tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
            attr="© OpenStreetMap contributors © CARTO",
            name="Light",
            overlay=False,
            control=True,
        ).add_to(map_obj)

    def _add_start_end_markers(self, map_obj: folium.Map, journey: Journey):
        """
        Add green start marker and red end marker to the map.

        Markers include popups with:
        - Location name (if geocoded)
        - Timestamp
        - Elevation

        Args:
            map_obj: Folium map object
            journey: Journey object with start/end data
        """
        first_wp = journey.waypoints[0]
        last_wp = journey.waypoints[-1]

        # GPX times are UTC; render them in the waypoint's own local time.
        start_local = to_local(journey.start_date, first_wp.longitude)
        end_local = to_local(journey.end_date, last_wp.longitude)

        # Start marker (green)
        start_popup = f"""
        <b>Journey Start</b><br>
        {start_local.strftime("%B %d, %Y %I:%M %p")}<br>
        {first_wp.elevation:.0f}m elevation
        """
        if journey.start_location:
            start_popup = f"""
            <b>Journey Start</b><br>
            {journey.start_location.place_label}<br>
            {start_local.strftime("%B %d, %Y %I:%M %p")}<br>
            {first_wp.elevation:.0f}m elevation
            """

        folium.Marker(
            location=[first_wp.latitude, first_wp.longitude],
            popup=folium.Popup(start_popup, max_width=300),
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
            tooltip="Journey Start",
        ).add_to(map_obj)

        # End marker (red)
        end_popup = f"""
        <b>Journey End</b><br>
        {end_local.strftime("%B %d, %Y %I:%M %p")}<br>
        {last_wp.elevation:.0f}m elevation
        """
        if journey.end_location:
            end_popup = f"""
            <b>Journey End</b><br>
            {journey.end_location.place_label}<br>
            {end_local.strftime("%B %d, %Y %I:%M %p")}<br>
            {last_wp.elevation:.0f}m elevation
            """

        folium.Marker(
            location=[last_wp.latitude, last_wp.longitude],
            popup=folium.Popup(end_popup, max_width=300),
            icon=folium.Icon(color="red", icon="stop", prefix="fa"),
            tooltip="Journey End",
        ).add_to(map_obj)

    def _add_photo_markers(self, map_obj: folium.Map, photos: list[MatchedPhoto]):
        """
        Add camera icon markers for GPS-matched photos.

        Each marker displays a popup with:
        - Photo thumbnail (if available)
        - Location name
        - Timestamp
        - Camera info (if available)

        Args:
            map_obj: Folium map object
            photos: List of GPS-matched photos with coordinates
        """
        if not photos:
            logger.info("No photos to add to map")
            return

        logger.info(f"Adding {len(photos)} photo markers to map")

        for photo in photos:
            # Build popup HTML
            photo_local = to_local(photo.gps_timestamp, photo.gps_longitude)
            popup_html = f"""
            <div style="width: 200px">
                <b>Photo</b><br>
                <i>{photo_local.strftime("%B %d, %I:%M %p")}</i>
            """

            if photo.location_name:
                popup_html += f"<br>{photo.location_name}"

            if photo.metadata and photo.metadata.camera_make:
                popup_html += f"<br><small>{photo.metadata.camera_make}"
                if photo.metadata.camera_model:
                    popup_html += f" {photo.metadata.camera_model}"
                popup_html += "</small>"

            popup_html += "</div>"

            folium.Marker(
                location=[photo.gps_latitude, photo.gps_longitude],
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color="blue", icon="camera", prefix="fa"),
                tooltip="Photo",
            ).add_to(map_obj)

    def generate_journey_map(
        self,
        journey: Journey,
        output_path: str | Path,
        include_photos: bool = True,
        include_fullscreen: bool = True,
    ) -> Path:
        """
        Generate an interactive Folium/Leaflet map for a GPS journey.

        Creates a standalone HTML file with:
        - Simplified route polyline (10K → 500 points)
        - Start/end markers
        - Photo location markers (if available)
        - Multiple tile layer options
        - Fullscreen control
        - Auto-fitted bounds

        The output HTML can be embedded in Hugo pages using the mapembed shortcode:
        {{< mapembed map="/maps/trip.html" >}}

        Args:
            journey: Journey object with GPS waypoints and optional photos
            output_path: Path to save the HTML map file
            include_photos: Whether to add photo markers (default: True)
            include_fullscreen: Add fullscreen button (default: True)

        Returns:
            Path to the generated HTML file

        Raises:
            ValueError: If journey has no waypoints
            IOError: If output path is not writable

        Example:
            >>> from gps_journey.core.gpx_parser import GPXParser
            >>> journey = GPXParser().parse("track.gpx")
            >>> generator = MapGenerator()
            >>> map_path = generator.generate_journey_map(
            ...     journey=journey,
            ...     output_path="static/maps/trip.html"
            ... )
            >>> print(f"Map saved to {map_path}")
            Map saved to static/maps/trip.html
        """
        output_path = Path(output_path)

        if not journey.waypoints:
            raise ValueError("Journey has no waypoints - cannot generate map")

        logger.info(f"Generating map for journey with {len(journey.waypoints)} waypoints")

        # Extract waypoint coordinates
        all_points = [(wp.latitude, wp.longitude) for wp in journey.waypoints]

        # Simplify polyline for performance
        logger.info(
            f"Simplifying polyline (tolerance={self.simplify_tolerance}, min={self.min_points})"
        )
        simplified_points = simplify_polyline(
            all_points, tolerance=self.simplify_tolerance, min_points=self.min_points
        )

        # Log compression stats
        stats = calculate_reduction(len(all_points), len(simplified_points))
        logger.info(
            f"Polyline simplified: {len(all_points)} → {len(simplified_points)} points "
            f"({stats['reduction_percent']:.1f}% reduction, {stats['compression_ratio']:.1f}:1 ratio)"
        )

        # Calculate map center and bounds
        center = self._calculate_center(all_points)
        bounds = self._calculate_bounds(all_points)

        # Create base map
        map_obj = folium.Map(
            location=center, tiles="OpenStreetMap", zoom_start=8, control_scale=True
        )

        # Add alternative tile layers
        self._add_tile_layers(map_obj)

        # Add layer control
        folium.LayerControl(position="topright").add_to(map_obj)

        # Add route polyline
        folium.PolyLine(
            locations=simplified_points,
            color=self.route_color,
            weight=self.route_weight,
            opacity=self.route_opacity,
            tooltip="Journey Route",
        ).add_to(map_obj)

        # Add start/end markers
        self._add_start_end_markers(map_obj, journey)

        # Add photo markers if available and requested
        if include_photos and journey.photos:
            logger.info(f"Journey has {len(journey.photos)} photos")
            # Filter for photos with GPS coordinates (MatchedPhoto instances)
            gps_photos = [p for p in journey.photos if hasattr(p, "gps_latitude")]
            if gps_photos:
                self._add_photo_markers(map_obj, gps_photos)
        else:
            if include_photos:
                logger.info("No photos to include on map")

        # Add fullscreen control
        if include_fullscreen:
            plugins.Fullscreen(position="topleft").add_to(map_obj)

        # Fit map to route bounds with padding
        map_obj.fit_bounds(bounds, padding=[30, 30])

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save map
        _save_accessible(map_obj, output_path)
        logger.info(f"Map saved to {output_path}")

        return output_path

    def generate_daily_map(
        self, waypoints: list, day_number: int, journey_slug: str, output_dir: Path
    ) -> str:
        """
        Generate Folium map for a single day's route.

        Args:
            waypoints: List of Waypoint objects for the day
            day_number: Day number (1-indexed)
            journey_slug: Journey slug for filename
            output_dir: Directory to save map HTML

        Returns:
            Relative path for Hugo: /maps/{slug}-day{N}.html
        """
        if not waypoints:
            logger.warning(f"No waypoints for day {day_number}")
            return None

        # Convert waypoints to points
        points = [(wp.latitude, wp.longitude) for wp in waypoints]

        # Calculate center and bounds
        center = self._calculate_center(points)
        bounds = self._calculate_bounds(points)

        # Create map
        map_obj = folium.Map(location=center, zoom_start=10, tiles="OpenStreetMap")

        # Simplify polyline for performance
        simplified = simplify_polyline(points, tolerance=self.simplify_tolerance)
        if len(simplified) < self.min_points:
            simplified = points[: self.min_points]

        # Add route polyline with green color for day maps
        folium.PolyLine(
            locations=simplified,
            color="#10b981",  # Green to match theme
            weight=self.route_weight,
            opacity=self.route_opacity,
            tooltip=f"Day {day_number} Route",
        ).add_to(map_obj)

        # Add start marker (green) - GPX times are UTC, show local
        first_wp = waypoints[0]
        first_local = to_local(first_wp.timestamp, first_wp.longitude)
        folium.Marker(
            location=[first_wp.latitude, first_wp.longitude],
            popup=f"<b>Day {day_number} Start</b><br>{first_local.strftime('%I:%M %p')}",
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
            tooltip="Start",
        ).add_to(map_obj)

        # Add end marker (red) - GPX times are UTC, show local
        last_wp = waypoints[-1]
        last_local = to_local(last_wp.timestamp, last_wp.longitude)
        folium.Marker(
            location=[last_wp.latitude, last_wp.longitude],
            popup=f"<b>Day {day_number} End</b><br>{last_local.strftime('%I:%M %p')}",
            icon=folium.Icon(color="red", icon="stop", prefix="fa"),
            tooltip="End",
        ).add_to(map_obj)

        # Fit to bounds
        map_obj.fit_bounds(bounds, padding=[30, 30])

        # Generate filename and save
        filename = f"{journey_slug}-day{day_number}.html"
        output_path = Path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        _save_accessible(map_obj, output_path)
        logger.info(f"Daily map saved: {output_path}")

        # Return relative path for Hugo
        return f"/maps/{filename}"
