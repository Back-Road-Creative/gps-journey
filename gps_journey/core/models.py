"""Core domain models for GPS journey data."""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

# --- Locale, units and clock time derived from data, never hardcoded --------
# This repo publishes journeys from many regions. The region name, distance
# units and displayed clock times must all derive from the journey's own GPS
# data (geocoded country + longitude) so the same code serves Ireland, the US,
# and anywhere else without a hardcoded locale.

KM_TO_MILES = 0.621371

# Countries whose road distances are conventionally shown in miles.
_MILES_COUNTRIES = frozenset({"united states", "united states of america", "usa", "us"})


def uses_miles(country: str | None) -> bool:
    """Whether to render road distances in miles for this country.

    Defaults to metric (km) when the country is unknown so an ungeocoded
    journey never silently asserts imperial units.
    """
    return bool(country) and country.strip().lower() in _MILES_COUNTRIES


def format_distance_km(distance_km: float, *, miles: bool, decimals: int = 0) -> str:
    """Render a km distance in the region's units (mi for imperial, else km)."""
    if miles:
        return f"{distance_km * KM_TO_MILES:,.{decimals}f} mi"
    return f"{distance_km:,.{decimals}f} km"


def local_offset_hours(longitude: float) -> int:
    """Approximate whole-hour offset from UTC at this longitude (15 deg/hour).

    GPX timestamps are UTC; the camera clock and an operator's sense of the day
    are LOCAL. Deriving the offset from longitude keeps the code region-agnostic
    (no hardcoded timezone); ``local_day`` below buckets by the same offset.
    """
    return round(longitude / 15)


def to_local(timestamp: datetime, longitude: float) -> datetime:
    """Shift a UTC GPX timestamp to longitude-local solar time for display."""
    return timestamp + timedelta(hours=local_offset_hours(longitude))


def local_day(timestamp: datetime, longitude: float) -> date:
    """Calendar day at the waypoint's own location (see ``to_local``).

    Bucketing by this instead of the raw UTC date keeps one local evening's
    drive on one page even when it crosses UTC midnight far from Greenwich.
    """
    return to_local(timestamp, longitude).date()


def region_label(location: "Location | None") -> str | None:
    """Best human region name for a journey title/summary.

    Prefers the sub-national region (state) then country then county. Returns
    None when nothing is geocoded so callers omit the region rather than assert
    a wrong one (a US drive must never read "through Ireland").
    """
    if not location:
        return None
    return location.state or location.country or location.county


@dataclass(frozen=True)
class Location:
    """Geocoded location information."""

    latitude: float
    longitude: float
    name: str | None = None  # "Harbourview Head Lighthouse" or village name
    locality: str | None = None  # Townland/locality (e.g., "Ardbane")
    suburb: str | None = None  # Suburb or neighborhood
    city: str | None = None
    town: str | None = None  # OSM town (settlement smaller than a city)
    village: str | None = None  # OSM village (real rural populated place)
    hamlet: str | None = None  # OSM hamlet (rural postal cluster; least reliable)
    county: str | None = None
    state: str | None = None
    country: str | None = None
    address: str | None = None  # Full formatted address

    def __str__(self) -> str:
        """Human-readable location string."""
        parts = [
            p
            for p in [
                self.name,
                self.locality,
                self.suburb,
                self.city,
                self.county,
                self.state,
                self.country,
            ]
            if p
        ]
        return ", ".join(parts) if parts else f"{self.latitude:.4f}, {self.longitude:.4f}"

    @property
    def place_label(self) -> str | None:
        """Settlement-level place name for public labels (map start/end, etc.).

        Prefers a populated place (city/town/village/locality) over ``name``,
        which the geocoder fills with the nearest business POI a drive may only
        have passed near. Falls back to ``name`` then ``county``.
        """
        return self.city or self.town or self.village or self.locality or self.name or self.county

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "name": self.name,
            "locality": self.locality,
            "suburb": self.suburb,
            "city": self.city,
            "town": self.town,
            "village": self.village,
            "hamlet": self.hamlet,
            "county": self.county,
            "state": self.state,
            "country": self.country,
            "address": self.address,
        }


@dataclass(frozen=True)
class Waypoint:
    """GPS waypoint with optional metadata."""

    latitude: float
    longitude: float
    timestamp: datetime
    elevation: float | None = None  # meters
    name: str | None = None
    description: str | None = None
    location: Location | None = None  # Geocoded location

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timestamp": self.timestamp.isoformat(),
            "elevation": self.elevation,
            "name": self.name,
            "description": self.description,
            "location": self.location.to_dict() if self.location else None,
        }


@dataclass(frozen=True)
class Photo:
    """Photo with EXIF metadata and GPS coordinates."""

    filename: str
    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    camera: str | None = None
    lens: str | None = None
    iso: int | None = None
    aperture: str | None = None
    shutter_speed: str | None = None
    location: Location | None = None  # Geocoded location
    matched_waypoint_index: int | None = None  # Index in journey waypoints

    def has_gps(self) -> bool:
        """Check if photo has valid GPS coordinates.

        Returns False for None values or invalid 0,0 coordinates
        (which indicate junk GPS data, not actual location).
        """
        if self.latitude is None or self.longitude is None:
            return False
        # Reject 0,0 coordinates (null island) - these are invalid GPS tags
        return not (abs(self.latitude) < 0.001 and abs(self.longitude) < 0.001)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "filename": self.filename,
            "timestamp": self.timestamp.isoformat(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "camera": self.camera,
            "lens": self.lens,
            "iso": self.iso,
            "aperture": self.aperture,
            "shutter_speed": self.shutter_speed,
            "location": self.location.to_dict() if self.location else None,
            "matched_waypoint_index": self.matched_waypoint_index,
        }


@dataclass(frozen=True)
class JourneyStatistics:
    """Calculated statistics for a journey."""

    total_distance_km: float
    total_distance_miles: float
    total_elevation_gain_m: float
    total_elevation_loss_m: float
    moving_time_seconds: int
    stopped_time_seconds: int
    average_speed_kmh: float
    max_speed_kmh: float
    min_elevation_m: float
    max_elevation_m: float

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_distance_km": round(self.total_distance_km, 2),
            "total_distance_miles": round(self.total_distance_miles, 2),
            "total_elevation_gain_m": round(self.total_elevation_gain_m, 1),
            "total_elevation_loss_m": round(self.total_elevation_loss_m, 1),
            "moving_time_seconds": self.moving_time_seconds,
            "stopped_time_seconds": self.stopped_time_seconds,
            "average_speed_kmh": round(self.average_speed_kmh, 1),
            "max_speed_kmh": round(self.max_speed_kmh, 1),
            "min_elevation_m": round(self.min_elevation_m, 1),
            "max_elevation_m": round(self.max_elevation_m, 1),
        }


@dataclass(frozen=True)
class DayStatistics:
    """Statistics for a single day of travel."""

    day_number: int
    date: date
    distance_km: float
    duration_hours: float
    elevation_gain_m: float
    elevation_loss_m: float
    photo_count: int
    waypoint_count: int
    start_time: datetime
    end_time: datetime
    start_location: Location | None = None
    end_location: Location | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "day_number": self.day_number,
            "date": self.date.isoformat(),
            "distance_km": round(self.distance_km, 1),
            "duration_hours": round(self.duration_hours, 1),
            "elevation_gain_m": int(self.elevation_gain_m),
            "elevation_loss_m": int(self.elevation_loss_m),
            "photo_count": self.photo_count,
            "waypoint_count": self.waypoint_count,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "start_location": self.start_location.to_dict() if self.start_location else None,
            "end_location": self.end_location.to_dict() if self.end_location else None,
        }


@dataclass(frozen=True)
class PhotoGroup:
    """Photos grouped by location."""

    location_name: str
    latitude: float
    longitude: float
    photos: tuple[Photo, ...]

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "photos": [photo.to_dict() for photo in self.photos],
        }


@dataclass(frozen=True)
class DayBreakdown:
    """Complete daily breakdown with waypoints and photos."""

    statistics: DayStatistics
    waypoints: tuple[Waypoint, ...]
    photos: tuple[Photo, ...]
    photo_groups: tuple[PhotoGroup, ...]
    locations_visited: tuple[str, ...]  # Ordered location names
    narrative: str  # Auto-generated summary
    map_file: str | None = None  # Relative path: /maps/{slug}-day{N}.html
    gpx_file: str | None = None  # Relative path: /gpx/{slug}-day{N}.gpx

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "statistics": self.statistics.to_dict(),
            "waypoints": [w.to_dict() for w in self.waypoints],
            "photos": [p.to_dict() for p in self.photos],
            "photo_groups": [pg.to_dict() for pg in self.photo_groups],
            "locations_visited": list(self.locations_visited),
            "narrative": self.narrative,
            "map_file": self.map_file,
            "gpx_file": self.gpx_file,
        }


@dataclass(frozen=True)
class Journey:
    """Complete journey with GPS data, photos, and metadata."""

    start_date: datetime
    end_date: datetime
    waypoints: tuple[Waypoint, ...] = field(default_factory=tuple)
    photos: tuple[Photo, ...] = field(default_factory=tuple)
    statistics: JourneyStatistics | None = None
    start_location: Location | None = None
    end_location: Location | None = None
    title: str | None = None
    description: str | None = None
    daily_breakdowns: tuple[DayBreakdown, ...] = field(default_factory=tuple)

    @property
    def duration_days(self) -> int:
        """Calculate journey duration in days."""
        delta = self.end_date - self.start_date
        return delta.days

    @property
    def duration_hours(self) -> float:
        """Calculate journey duration in hours."""
        delta = self.end_date - self.start_date
        return delta.total_seconds() / 3600

    def with_waypoints(self, waypoints: list[Waypoint]) -> "Journey":
        """Return new Journey with updated waypoints."""
        return replace(self, waypoints=tuple(waypoints))

    def with_photos(self, photos: list[Photo]) -> "Journey":
        """Return new Journey with updated photos."""
        return replace(self, photos=tuple(photos))

    def with_statistics(self, stats: JourneyStatistics) -> "Journey":
        """Return new Journey with statistics."""
        return replace(self, statistics=stats)

    def with_locations(self, start: Location, end: Location) -> "Journey":
        """Return new Journey with start/end locations."""
        return replace(self, start_location=start, end_location=end)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "duration_days": self.duration_days,
            "duration_hours": round(self.duration_hours, 1),
            "waypoints": [w.to_dict() for w in self.waypoints],
            "photos": [p.to_dict() for p in self.photos],
            "statistics": self.statistics.to_dict() if self.statistics else None,
            "start_location": self.start_location.to_dict() if self.start_location else None,
            "end_location": self.end_location.to_dict() if self.end_location else None,
            "title": self.title,
            "description": self.description,
        }
