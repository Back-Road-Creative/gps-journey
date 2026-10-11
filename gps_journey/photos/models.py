"""Data models for photo integration."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Photo:
    """Represents a photo from Google Photos."""

    id: str
    filename: str
    base_url: str
    creation_time: datetime
    width: int
    height: int
    mime_type: str

    @property
    def download_url(self) -> str:
        """Get URL for downloading full resolution photo."""
        return f"{self.base_url}=d"


@dataclass(frozen=True)
class PhotoMetadata:
    """EXIF metadata extracted from a photo."""

    photo_id: str
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    timestamp: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    iso: int | None = None
    aperture: float | None = None
    shutter_speed: str | None = None


@dataclass(frozen=True)
class MatchedPhoto:
    """Photo matched to a GPS timeline point."""

    photo: Photo
    metadata: PhotoMetadata
    gps_latitude: float
    gps_longitude: float
    gps_timestamp: datetime
    # Metres between the photo's own EXIF GPS fix and the matched track point.
    # None = not measured (a time-only match); never 0.0 as a placeholder.
    distance_meters: float | None
    time_offset_seconds: float
    location_name: str | None = None
    # Provenance of the capture time used for the match:
    # "exif" (PhotoMetadata.timestamp) or "photo_creation_time" (Photo.creation_time).
    timestamp_source: str | None = None
    # How the capture time was placed on the UTC timeline: "aware" (the timestamp
    # carried its own offset) or "camera_clock" (naive, interpreted with the
    # configured camera clock).
    clock_basis: str | None = None
    # "measured": the photo carried its own GPS fix and distance_meters compares
    # it to the track point. "inferred": location comes from the time match only.
    location_status: str = "inferred"
    # Seconds between the track points around the photo's time (the widest
    # adjacent interval when the photo sits exactly on a point); None when the
    # track does not bracket the photo (past either end, or a single point).
    track_gap_seconds: float | None = None
    # Time tolerance (seconds) that applied to this match.
    effective_tolerance_seconds: float | None = None


@dataclass(frozen=True)
class Album:
    """Represents a Google Photos album."""

    id: str
    title: str
    product_url: str
    media_items_count: int
    cover_photo_base_url: str | None = None
