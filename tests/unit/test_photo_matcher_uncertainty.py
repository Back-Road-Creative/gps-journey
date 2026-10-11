"""Unknown spatial distance and match uncertainty are explicit.

A time-only match must not claim zero spatial error: ``distance_meters`` is
``None`` unless the photo carries its own GPS fix to compare against. Matches
also record the time offset, the sparseness of the track around the photo, the
inferred/measured status and the tolerance that applied. A publication policy
can refuse sparse-track evidence.
"""

import math
from datetime import datetime, timedelta, timezone

from gps_journey.photos.matcher import PhotoMatcher, PublicationPolicy
from gps_journey.photos.models import MatchedPhoto, Photo, PhotoMetadata

UTC = timezone.utc
T0 = datetime(2022, 7, 1, 12, 0, tzinfo=UTC)
TRACK_LAT, TRACK_LON = 53.35, -6.26


def _photo(name: str = "IMG_0001.jpg") -> Photo:
    return Photo(
        id=name,
        filename=name,
        base_url="https://example.invalid/" + name,
        creation_time=T0,
        width=100,
        height=100,
        mime_type="image/jpeg",
    )


def _timeline(offsets_s: list[int]) -> list[tuple[datetime, float, float]]:
    return [(T0 + timedelta(seconds=s), TRACK_LAT, TRACK_LON) for s in offsets_s]


DENSE = _timeline(list(range(-300, 301, 60)))


def _match(
    ts_offset_s: int = 0,
    timeline=DENSE,
    lat: float | None = None,
    lon: float | None = None,
    **matcher_kwargs,
):
    photo = _photo()
    meta = PhotoMetadata(
        photo_id=photo.id,
        gps_latitude=lat,
        gps_longitude=lon,
        timestamp=T0 + timedelta(seconds=ts_offset_s),
    )
    return PhotoMatcher(**matcher_kwargs).match_photos_with_report([photo], [meta], timeline)


class TestDistance:
    def test_time_only_match_has_unknown_distance_not_zero(self):
        (m,) = _match().matched
        assert m.distance_meters is None
        assert m.location_status == "inferred"

    def test_legacy_list_api_also_reports_unknown_distance(self):
        photo = _photo()
        meta = PhotoMetadata(photo_id=photo.id, timestamp=T0)
        (m,) = PhotoMatcher().match_photos_to_timeline([photo], [meta], DENSE)
        assert m.distance_meters is None

    def test_photo_gps_yields_real_haversine_distance(self):
        # 0.001 degrees of latitude is ~111.2 m.
        (m,) = _match(lat=TRACK_LAT + 0.001, lon=TRACK_LON).matched
        assert m.location_status == "measured"
        assert m.distance_meters is not None
        assert math.isclose(m.distance_meters, 111.2, abs_tol=1.0)

    def test_photo_gps_at_the_track_point_measures_zero(self):
        (m,) = _match(lat=TRACK_LAT, lon=TRACK_LON).matched
        assert m.location_status == "measured"
        assert m.distance_meters == 0.0

    def test_partial_or_invalid_photo_gps_is_not_measured(self):
        for lat, lon in [(TRACK_LAT, None), (None, TRACK_LON), (91.0, 0.0), (0.0, 181.0)]:
            (m,) = _match(lat=lat, lon=lon).matched
            assert m.distance_meters is None, (lat, lon)
            assert m.location_status == "inferred"

    def test_nan_photo_gps_is_not_measured(self):
        (m,) = _match(lat=float("nan"), lon=TRACK_LON).matched
        assert m.distance_meters is None

    def test_gallery_metadata_handles_unknown_distance(self):
        photo = _photo()
        meta = PhotoMetadata(photo_id=photo.id, timestamp=T0)
        matcher = PhotoMatcher()
        matches = matcher.match_photos_to_timeline([photo], [meta], DENSE)
        gallery = matcher.generate_gallery_metadata(matches, journey_slug="x")
        assert gallery[0]["gps"] == {"lat": TRACK_LAT, "lon": TRACK_LON}


class TestUncertaintyFields:
    def test_records_time_offset_and_effective_tolerance(self):
        (m,) = _match(ts_offset_s=25, tolerance_minutes=2).matched
        assert m.time_offset_seconds == 25.0
        assert m.effective_tolerance_seconds == 120.0

    def test_time_offset_is_signed_from_nearest_point(self):
        (m,) = _match(ts_offset_s=25).matched
        assert m.gps_timestamp == T0
        assert m.time_offset_seconds == 25.0

    def test_dense_track_gap(self):
        (m,) = _match(ts_offset_s=25).matched
        assert m.track_gap_seconds == 60.0

    def test_sparse_track_gap_spans_the_bracketing_points(self):
        sparse = _timeline([0, 600])
        (m,) = _match(ts_offset_s=250, timeline=sparse, tolerance_minutes=5).matched
        assert m.track_gap_seconds == 600.0

    def test_photo_on_a_point_uses_widest_adjacent_interval(self):
        timeline = _timeline([-60, 0, 300])
        (m,) = _match(ts_offset_s=0, timeline=timeline).matched
        assert m.track_gap_seconds == 300.0

    def test_photo_past_track_end_has_unknown_gap(self):
        timeline = _timeline([0, 60, 120])
        (m,) = _match(ts_offset_s=200, timeline=timeline).matched
        assert m.track_gap_seconds is None

    def test_single_point_track_has_unknown_gap(self):
        (m,) = _match(ts_offset_s=30, timeline=_timeline([0])).matched
        assert m.track_gap_seconds is None


class TestPublicationPolicy:
    def test_no_policy_refuses_nothing(self):
        report = _match(timeline=_timeline([0, 600]), ts_offset_s=250)
        assert len(report.matched) == 1
        assert report.refused == []

    def test_sparse_track_match_is_refused_by_policy(self):
        policy = PublicationPolicy(max_track_gap_seconds=120)
        report = _match(
            timeline=_timeline([0, 600]),
            ts_offset_s=250,
            publication_policy=policy,
        )
        assert report.matched == []
        (refused,) = report.refused
        assert refused.reason == "sparse_track"
        assert isinstance(refused.match, MatchedPhoto)
        assert refused.match.track_gap_seconds == 600.0

    def test_dense_track_match_passes_policy(self):
        policy = PublicationPolicy(max_track_gap_seconds=120)
        report = _match(ts_offset_s=25, publication_policy=policy)
        assert len(report.matched) == 1
        assert report.refused == []

    def test_unknown_gap_is_refused_when_policy_sets_a_limit(self):
        policy = PublicationPolicy(max_track_gap_seconds=120)
        report = _match(
            timeline=_timeline([0, 60, 120]), ts_offset_s=200, publication_policy=policy
        )
        assert report.matched == []
        assert report.refused[0].reason == "sparse_track"

    def test_policy_without_limit_refuses_nothing(self):
        report = _match(
            timeline=_timeline([0, 600]), ts_offset_s=250, publication_policy=PublicationPolicy()
        )
        assert len(report.matched) == 1
