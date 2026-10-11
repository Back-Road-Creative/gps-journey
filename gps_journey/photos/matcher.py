"""Match photos to GPS timeline based on timestamps and coordinates."""

import logging
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import NamedTuple
from zoneinfo import ZoneInfo

from gps_journey.photos.models import MatchedPhoto, Photo, PhotoMetadata

logger = logging.getLogger(__name__)

# Reasons a photo is parked in MatchReport.needs_clock_decision.
NAIVE_NO_CLOCK = "naive_timestamp_no_clock"
AMBIGUOUS_LOCAL_TIME = "ambiguous_local_time"
NONEXISTENT_LOCAL_TIME = "nonexistent_local_time"

# Reason a match is withheld by a PublicationPolicy.
SPARSE_TRACK = "sparse_track"

CameraClock = tzinfo | timedelta | str | None


@dataclass(frozen=True)
class ClockDecision:
    """A photo whose capture time cannot be placed on the UTC timeline yet."""

    photo: Photo
    timestamp: datetime
    timestamp_source: str
    reason: str


@dataclass(frozen=True)
class PublicationPolicy:
    """Evidence bar a match must clear before it is published.

    Attributes:
        max_track_gap_seconds: Refuse a match whose surrounding track is sparser
            than this, or whose gap is unknown (photo not bracketed by track
            points). None disables the check.
    """

    max_track_gap_seconds: float | None = None

    def refusal_reason(self, match: MatchedPhoto) -> str | None:
        """Return why ``match`` may not be published, or None if it may."""
        if self.max_track_gap_seconds is not None and (
            match.track_gap_seconds is None or match.track_gap_seconds > self.max_track_gap_seconds
        ):
            return SPARSE_TRACK
        return None


@dataclass(frozen=True)
class RefusedMatch:
    """A match withheld by the publication policy."""

    match: MatchedPhoto
    reason: str


@dataclass
class MatchReport:
    """Outcome of one matching pass, split by what the caller must do next."""

    matched: list[MatchedPhoto] = field(default_factory=list)
    refused: list[RefusedMatch] = field(default_factory=list)
    needs_clock_decision: list[ClockDecision] = field(default_factory=list)
    unmatched: list[Photo] = field(default_factory=list)


class _TrackHit(NamedTuple):
    timestamp: datetime
    latitude: float
    longitude: float
    time_offset_seconds: float
    track_gap_seconds: float | None


def _coerce_camera_clock(clock: CameraClock) -> tzinfo | None:
    if clock is None or isinstance(clock, tzinfo):
        return clock
    if isinstance(clock, timedelta):
        return timezone(clock)
    if isinstance(clock, str):
        return ZoneInfo(clock)
    raise TypeError(
        "camera_clock must be a tzinfo, a timedelta UTC offset, an IANA zone name or None; "
        f"got {type(clock).__name__}"
    )


class PhotoMatcher:
    """Match photos to GPS track timeline."""

    def __init__(
        self,
        tolerance_minutes: int = 5,
        camera_clock: CameraClock = None,
        publication_policy: PublicationPolicy | None = None,
    ):
        """
        Initialize photo matcher.

        Args:
            tolerance_minutes: Time tolerance window for matching (default: +-5 minutes)
            camera_clock: How to read a *naive* photo timestamp (EXIF carries no
                zone by default): a tzinfo / IANA zone name (DST-aware) or a
                timedelta fixed UTC offset. When None, a naive timestamp is never
                guessed: the photo is reported in ``needs_clock_decision``. Aware
                timestamps are always used as-is.
            publication_policy: Optional evidence bar. Matches that fail it are
                returned in ``MatchReport.refused`` instead of ``matched``.
        """
        self.tolerance_seconds = tolerance_minutes * 60
        self.publication_policy = publication_policy
        self.camera_clock = _coerce_camera_clock(camera_clock)

    def match_photos_to_timeline(
        self,
        photos: list[Photo],
        photo_metadata: list[PhotoMetadata],
        gps_timeline: list[tuple[datetime, float, float]],
    ) -> list[MatchedPhoto]:
        """
        Match photos to GPS timeline based on timestamps.

        Convenience wrapper over :meth:`match_photos_with_report` that returns
        only the matches. Photos parked for a clock decision are logged as a
        warning; use the report API to act on them.

        Args:
            photos: List of Photo objects
            photo_metadata: List of PhotoMetadata objects (same order as photos)
            gps_timeline: List of (timestamp, lat, lon) tuples, sorted by time

        Returns:
            List of MatchedPhoto objects for successfully matched photos
        """
        report = self.match_photos_with_report(photos, photo_metadata, gps_timeline)
        if report.needs_clock_decision:
            logger.warning(
                "%d photo(s) need a camera-clock decision and were not matched; "
                "configure PhotoMatcher(camera_clock=...) or use match_photos_with_report()",
                len(report.needs_clock_decision),
            )
        return report.matched

    def match_photos_with_report(
        self,
        photos: list[Photo],
        photo_metadata: list[PhotoMetadata],
        gps_timeline: list[tuple[datetime, float, float]],
    ) -> MatchReport:
        """
        Match photos to the GPS timeline and report every outcome.

        Args:
            photos: List of Photo objects
            photo_metadata: List of PhotoMetadata objects (same order as photos)
            gps_timeline: List of (timestamp, lat, lon) tuples

        Returns:
            MatchReport with matched photos, photos that need a clock decision
            (naive timestamp with no camera clock, or a DST-ambiguous or
            nonexistent local time) and photos with no track point in tolerance.
        """
        report = MatchReport()

        if len(photos) != len(photo_metadata):
            raise ValueError(
                f"Photo count ({len(photos)}) does not match metadata count ({len(photo_metadata)})"
            )

        if not gps_timeline:
            logger.warning("GPS timeline is empty, cannot match photos")
            report.unmatched.extend(photos)
            return report

        # Sort GPS timeline by timestamp (should already be sorted, but ensure it)
        sorted_timeline = sorted(gps_timeline, key=lambda x: x[0])

        for photo, metadata in zip(photos, photo_metadata, strict=False):
            # Prefer EXIF, fall back to Google Photos creation time
            if metadata.timestamp:
                photo_timestamp, source = metadata.timestamp, "exif"
            else:
                photo_timestamp, source = photo.creation_time, "photo_creation_time"

            instants, basis, problem = self._resolve_capture_instants(photo_timestamp)
            if problem in (NAIVE_NO_CLOCK, NONEXISTENT_LOCAL_TIME):
                report.needs_clock_decision.append(
                    ClockDecision(photo, photo_timestamp, source, problem)
                )
                continue

            hits = [
                hit
                for instant in instants
                if (hit := self._find_nearest_gps_point(instant, sorted_timeline)) is not None
            ]

            if problem == AMBIGUOUS_LOCAL_TIME and len(hits) > 1:
                # Both readings of the repeated hour sit on the track: guessing
                # would be a coin flip, so ask for a decision.
                report.needs_clock_decision.append(
                    ClockDecision(photo, photo_timestamp, source, problem)
                )
                continue

            if not hits:
                report.unmatched.append(photo)
                logger.debug(
                    "No GPS match for %s (timestamp: %s)",
                    photo.filename,
                    photo_timestamp,
                )
                continue

            hit = hits[0]
            distance_m = self._measure_distance(metadata, hit.latitude, hit.longitude)
            match = MatchedPhoto(
                photo=photo,
                metadata=metadata,
                gps_latitude=hit.latitude,
                gps_longitude=hit.longitude,
                gps_timestamp=hit.timestamp,
                distance_meters=distance_m,
                time_offset_seconds=hit.time_offset_seconds,
                timestamp_source=source,
                clock_basis=basis,
                location_status="inferred" if distance_m is None else "measured",
                track_gap_seconds=hit.track_gap_seconds,
                effective_tolerance_seconds=float(self.tolerance_seconds),
            )
            reason = (
                self.publication_policy.refusal_reason(match) if self.publication_policy else None
            )
            if reason:
                report.refused.append(RefusedMatch(match, reason))
                continue
            report.matched.append(match)
            logger.debug(
                "Matched %s: time offset=%.1fs, distance=%s",
                photo.filename,
                hit.time_offset_seconds,
                "unmeasured" if distance_m is None else f"{distance_m:.1f}m",
            )

        logger.info(
            "Matched %d/%d photos to GPS timeline "
            "(%d unmatched, %d need a clock decision, %d refused by policy)",
            len(report.matched),
            len(photos),
            len(report.unmatched),
            len(report.needs_clock_decision),
            len(report.refused),
        )

        return report

    def _resolve_capture_instants(
        self, dt: datetime
    ) -> tuple[list[datetime], str | None, str | None]:
        """
        Place a photo timestamp on the UTC timeline.

        Returns:
            (candidate UTC instants, clock basis, problem). ``problem`` is None
            when there is exactly one instant; NAIVE_NO_CLOCK / NONEXISTENT_LOCAL_TIME
            with no instants; AMBIGUOUS_LOCAL_TIME with two candidates for the
            caller to disambiguate against the track.
        """
        if dt.tzinfo is not None:
            return [dt.astimezone(timezone.utc)], "aware", None

        if self.camera_clock is None:
            return [], None, NAIVE_NO_CLOCK

        # A wall-clock time is real for a fold only if it survives a round trip
        # through UTC; the repeated hour has two valid folds, the gap has none.
        instants: list[datetime] = []
        for fold in (0, 1):
            local = dt.replace(tzinfo=self.camera_clock, fold=fold)
            utc = local.astimezone(timezone.utc)
            round_trip = utc.astimezone(self.camera_clock).replace(tzinfo=None, fold=0)
            if round_trip == dt and utc not in instants:
                instants.append(utc)
        if not instants:
            return [], "camera_clock", NONEXISTENT_LOCAL_TIME
        if len(instants) > 1:
            return instants, "camera_clock", AMBIGUOUS_LOCAL_TIME
        return instants, "camera_clock", None

    @staticmethod
    def _timeline_utc(dt: datetime) -> datetime:
        """
        Timeline (GPX) times as timezone-aware UTC.

        GPX 1.1 defines track times as UTC, so a naive timeline timestamp is
        read as UTC. This never applies to camera timestamps.
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _measure_distance(metadata: PhotoMetadata, lat: float, lon: float) -> float | None:
        """Metres from the photo's own GPS fix to a track point; None if it has no valid fix."""
        p_lat, p_lon = metadata.gps_latitude, metadata.gps_longitude
        if p_lat is None or p_lon is None:
            return None
        if not (math.isfinite(p_lat) and math.isfinite(p_lon)):
            return None
        if not (-90.0 <= p_lat <= 90.0 and -180.0 <= p_lon <= 180.0):
            return None
        return PhotoMatcher.calculate_haversine_distance(p_lat, p_lon, lat, lon)

    def _find_nearest_gps_point(
        self,
        photo_timestamp: datetime,
        gps_timeline: list[tuple[datetime, float, float]],
        tolerance_seconds: float | None = None,
    ) -> _TrackHit | None:
        """
        Find the nearest GPS point to a photo timestamp within tolerance.

        Uses binary search for efficiency.

        Args:
            photo_timestamp: When photo was taken (timezone-aware)
            gps_timeline: Sorted list of (timestamp, lat, lon)
            tolerance_seconds: Maximum time difference allowed
                (default: the matcher's tolerance)

        Returns:
            _TrackHit (timestamp, lat, lon, signed time offset, surrounding track gap)
            or None if no match within tolerance
        """
        if tolerance_seconds is None:
            tolerance_seconds = self.tolerance_seconds

        if not gps_timeline:
            return None

        if photo_timestamp.tzinfo is None:
            raise ValueError(
                "photo_timestamp must be timezone-aware; resolve the camera clock first"
            )

        # Binary search for nearest point
        left, right = 0, len(gps_timeline) - 1
        nearest_idx = 0
        min_time_diff = float("inf")

        while left <= right:
            mid = (left + right) // 2
            gps_time = self._timeline_utc(gps_timeline[mid][0])

            time_diff = abs((photo_timestamp - gps_time).total_seconds())

            if time_diff < min_time_diff:
                min_time_diff = time_diff
                nearest_idx = mid

            if photo_timestamp < gps_time:
                right = mid - 1
            else:
                left = mid + 1

        # Check if nearest point is within tolerance
        if min_time_diff > tolerance_seconds:
            return None

        gps_time, gps_lat, gps_lon = gps_timeline[nearest_idx]
        gps_time = self._timeline_utc(gps_time)

        # Calculate time offset (positive = photo after GPS, negative = photo before GPS)
        time_offset = (photo_timestamp - gps_time).total_seconds()

        return _TrackHit(
            gps_time,
            gps_lat,
            gps_lon,
            time_offset,
            self._track_gap_seconds(photo_timestamp, gps_timeline),
        )

    def _track_gap_seconds(
        self, photo_timestamp: datetime, gps_timeline: list[tuple[datetime, float, float]]
    ) -> float | None:
        """
        Seconds between the track points surrounding ``photo_timestamp``.

        A photo exactly on a point takes the widest interval adjacent to it.
        None when the track does not bracket the photo (past either end) or has
        a single point: sparseness is unknown, not zero.
        """

        # O(log n): bisect on the timeline itself, keyed to aware UTC times.
        def at(i: int) -> datetime:
            return self._timeline_utc(gps_timeline[i][0])

        def key(p: tuple[datetime, float, float]) -> datetime:
            return self._timeline_utc(p[0])

        n = len(gps_timeline)
        lo = bisect_left(gps_timeline, photo_timestamp, key=key)  # first index with time >= photo
        hi = bisect_right(gps_timeline, photo_timestamp, key=key)  # first index with time > photo
        if lo < hi:  # exact hit on the point at lo
            gaps = []
            if lo > 0:
                gaps.append((at(lo) - at(lo - 1)).total_seconds())
            if hi < n:
                gaps.append((at(hi) - at(lo)).total_seconds())
            return max(gaps) if gaps else None
        if lo == 0 or lo == n:
            return None
        return (at(lo) - at(lo - 1)).total_seconds()

    def generate_gallery_metadata(
        self,
        matched_photos: list[MatchedPhoto],
        base_path: str = "images/journeys",
        journey_slug: str = "",
    ) -> list[dict]:
        """
        Generate Hugo frontmatter gallery metadata.

        Args:
            matched_photos: List of matched photos
            base_path: Base path for images in Hugo site
            journey_slug: Journey slug for organizing photos

        Returns:
            List of gallery item dictionaries for Hugo frontmatter
        """
        gallery = []

        for idx, matched in enumerate(matched_photos, start=1):
            photo_filename = f"photo-{idx:03d}.jpg"
            thumb_filename = f"thumb-{idx:03d}.jpg"

            item = {
                "path": f"{base_path}/{journey_slug}/{photo_filename}",
                "thumb": f"{base_path}/{journey_slug}/{thumb_filename}",
                "caption": matched.photo.filename.rsplit(".", 1)[0],  # Remove extension
                "timestamp": matched.gps_timestamp.isoformat(),
                "gps": {
                    "lat": round(matched.gps_latitude, 6),
                    "lon": round(matched.gps_longitude, 6),
                },
            }

            # Add location name if available
            if matched.location_name:
                item["location"] = matched.location_name

            # Add camera info if available
            if matched.metadata.camera_make or matched.metadata.camera_model:
                camera_parts = []
                if matched.metadata.camera_make:
                    camera_parts.append(matched.metadata.camera_make)
                if matched.metadata.camera_model:
                    camera_parts.append(matched.metadata.camera_model)
                item["camera"] = " ".join(camera_parts)

            # Add photo settings if available
            settings = []
            if matched.metadata.iso:
                settings.append(f"ISO {matched.metadata.iso}")
            if matched.metadata.aperture:
                settings.append(f"f/{matched.metadata.aperture:.1f}")
            if matched.metadata.shutter_speed:
                settings.append(matched.metadata.shutter_speed)

            if settings:
                item["settings"] = " • ".join(settings)

            gallery.append(item)

        logger.info("Generated gallery metadata for %d photos", len(gallery))
        return gallery

    @staticmethod
    def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two GPS points using Haversine formula.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Distance in meters
        """
        from math import asin, cos, radians, sin, sqrt

        # Earth radius in meters
        R = 6371000

        # Convert to radians
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        delta_lat = radians(lat2 - lat1)
        delta_lon = radians(lon2 - lon1)

        # Haversine formula
        a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        c = 2 * asin(sqrt(a))

        return R * c
