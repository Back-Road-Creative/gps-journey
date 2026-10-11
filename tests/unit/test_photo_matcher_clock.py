"""A naive camera timestamp is never silently treated as UTC.

The matcher needs an explicit camera clock (fixed UTC offset or IANA zone) to
place a naive EXIF/creation timestamp on the GPS timeline. Without one the
photo lands in ``needs_clock_decision`` instead of matching. Aware timestamps
are used as-is. DST-ambiguous local times are resolved only when the timeline
picks exactly one candidate; nonexistent local times are refused.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from gps_journey.photos.matcher import PhotoMatcher
from gps_journey.photos.models import Photo, PhotoMetadata

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
DUBLIN = ZoneInfo("Europe/Dublin")


def _photo(name: str = "IMG_0001.jpg", creation_time: datetime | None = None) -> Photo:
    return Photo(
        id=name,
        filename=name,
        base_url="https://example.invalid/" + name,
        creation_time=creation_time or datetime(2000, 1, 1, tzinfo=UTC),
        width=100,
        height=100,
        mime_type="image/jpeg",
    )


def _meta(name: str, ts: datetime | None) -> PhotoMetadata:
    return PhotoMetadata(photo_id=name, timestamp=ts)


def _timeline(center_utc: datetime, span_min: int = 3) -> list[tuple[datetime, float, float]]:
    """One point per minute, +-span_min around center, lat/lon fixed."""
    return [
        (center_utc + timedelta(minutes=m), 53.35, -6.26) for m in range(-span_min, span_min + 1)
    ]


def _run(matcher, ts, timeline, creation_time=None, meta_ts="use_ts"):
    photo = _photo(creation_time=creation_time)
    meta = _meta(photo.id, ts if meta_ts == "use_ts" else meta_ts)
    return matcher.match_photos_with_report([photo], [meta], timeline)


class TestUnconfiguredNaiveClock:
    def test_naive_timestamp_without_clock_is_not_matched(self):
        # 12:00 naive would match a 12:00 UTC track point if silently taken as UTC.
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        report = _run(PhotoMatcher(), datetime(2022, 7, 1, 12, 0), timeline)
        assert report.matched == []
        assert [d.reason for d in report.needs_clock_decision] == ["naive_timestamp_no_clock"]
        assert report.needs_clock_decision[0].photo.filename == "IMG_0001.jpg"

    def test_legacy_list_api_does_not_match_naive_without_clock(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        photo = _photo()
        matcher = PhotoMatcher()
        got = matcher.match_photos_to_timeline(
            [photo], [_meta(photo.id, datetime(2022, 7, 1, 12, 0))], timeline
        )
        assert got == []

    def test_naive_creation_time_fallback_also_needs_clock(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        report = _run(
            PhotoMatcher(),
            None,
            timeline,
            creation_time=datetime(2022, 7, 1, 12, 0),
            meta_ts=None,
        )
        assert report.matched == []
        assert report.needs_clock_decision[0].reason == "naive_timestamp_no_clock"

    def test_off_track_naive_photo_still_needs_clock_not_unmatched(self):
        # The clock question is asked before any timeline comparison.
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        report = _run(PhotoMatcher(), datetime(2030, 1, 1, 0, 0), timeline)
        assert len(report.needs_clock_decision) == 1
        assert report.unmatched == []


class TestConfiguredClock:
    def test_fixed_offset_shifts_naive_time_to_utc(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=timedelta(hours=1))
        report = _run(matcher, datetime(2022, 7, 1, 13, 0), timeline)
        assert report.needs_clock_decision == []
        (m,) = report.matched
        assert m.gps_timestamp == datetime(2022, 7, 1, 12, 0, tzinfo=UTC)
        assert m.time_offset_seconds == 0.0
        assert m.clock_basis == "camera_clock"
        assert m.timestamp_source == "exif"

    def test_wrong_offset_does_not_match(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=timedelta(hours=-5))
        report = _run(matcher, datetime(2022, 7, 1, 13, 0), timeline)
        assert report.matched == []
        assert len(report.unmatched) == 1

    def test_iana_zone_uses_summer_offset(self):
        # Dublin is UTC+1 in July.
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=DUBLIN)
        report = _run(matcher, datetime(2022, 7, 1, 13, 0), timeline)
        assert report.matched[0].gps_timestamp == datetime(2022, 7, 1, 12, 0, tzinfo=UTC)

    def test_iana_zone_uses_winter_offset(self):
        # Dublin is UTC+0 in January.
        timeline = _timeline(datetime(2022, 1, 15, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=DUBLIN)
        report = _run(matcher, datetime(2022, 1, 15, 12, 0), timeline)
        assert report.matched[0].time_offset_seconds == 0.0

    def test_iana_zone_name_string_is_accepted(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock="Europe/Dublin")
        report = _run(matcher, datetime(2022, 7, 1, 13, 0), timeline)
        assert len(report.matched) == 1

    def test_creation_time_fallback_uses_clock_and_records_source(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=timedelta(hours=1))
        report = _run(
            matcher, None, timeline, creation_time=datetime(2022, 7, 1, 13, 0), meta_ts=None
        )
        assert report.matched[0].timestamp_source == "photo_creation_time"
        assert report.matched[0].clock_basis == "camera_clock"

    def test_invalid_clock_type_is_rejected(self):
        with pytest.raises(TypeError):
            PhotoMatcher(camera_clock=3600)  # type: ignore[arg-type]


class TestAwareTimestamps:
    def test_aware_utc_matches_without_any_clock(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        report = _run(PhotoMatcher(), datetime(2022, 7, 1, 12, 0, tzinfo=UTC), timeline)
        (m,) = report.matched
        assert m.time_offset_seconds == 0.0
        assert m.clock_basis == "aware"

    def test_aware_non_utc_is_converted_and_ignores_configured_clock(self):
        timeline = _timeline(datetime(2022, 7, 1, 12, 0, tzinfo=UTC))
        # 14:00+02:00 == 12:00Z; the configured -5h clock must not be applied.
        aware = datetime(2022, 7, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
        matcher = PhotoMatcher(camera_clock=timedelta(hours=-5))
        report = _run(matcher, aware, timeline)
        assert report.matched[0].gps_timestamp == datetime(2022, 7, 1, 12, 0, tzinfo=UTC)
        assert report.matched[0].time_offset_seconds == 0.0


class TestDstEdges:
    def test_ambiguous_time_resolved_when_timeline_covers_one_candidate(self):
        # 2022-11-06 01:30 New York happens twice: 05:30Z (EDT) and 06:30Z (EST).
        timeline = _timeline(datetime(2022, 11, 6, 5, 30, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        report = _run(matcher, datetime(2022, 11, 6, 1, 30), timeline)
        assert report.needs_clock_decision == []
        assert report.matched[0].gps_timestamp == datetime(2022, 11, 6, 5, 30, tzinfo=UTC)

    def test_ambiguous_time_resolved_to_second_candidate(self):
        timeline = _timeline(datetime(2022, 11, 6, 6, 30, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        report = _run(matcher, datetime(2022, 11, 6, 1, 30), timeline)
        assert report.matched[0].gps_timestamp == datetime(2022, 11, 6, 6, 30, tzinfo=UTC)

    def test_ambiguous_time_needs_decision_when_both_candidates_on_track(self):
        timeline = _timeline(datetime(2022, 11, 6, 5, 30, tzinfo=UTC)) + _timeline(
            datetime(2022, 11, 6, 6, 30, tzinfo=UTC)
        )
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        report = _run(matcher, datetime(2022, 11, 6, 1, 30), timeline)
        assert report.matched == []
        assert [d.reason for d in report.needs_clock_decision] == ["ambiguous_local_time"]

    def test_ambiguous_time_off_track_is_unmatched_not_a_clock_question(self):
        timeline = _timeline(datetime(2022, 11, 7, 12, 0, tzinfo=UTC))
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        report = _run(matcher, datetime(2022, 11, 6, 1, 30), timeline)
        assert report.matched == []
        assert report.needs_clock_decision == []
        assert len(report.unmatched) == 1

    def test_nonexistent_local_time_needs_decision(self):
        # 2022-03-13 02:30 does not exist in New York (spring-forward gap).
        timeline = _timeline(datetime(2022, 3, 13, 7, 30, tzinfo=UTC), span_min=90)
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        report = _run(matcher, datetime(2022, 3, 13, 2, 30), timeline)
        assert report.matched == []
        assert [d.reason for d in report.needs_clock_decision] == ["nonexistent_local_time"]

    def test_times_either_side_of_the_gap_match_normally(self):
        matcher = PhotoMatcher(camera_clock=NEW_YORK)
        before = _run(
            matcher,
            datetime(2022, 3, 13, 1, 30),
            _timeline(datetime(2022, 3, 13, 6, 30, tzinfo=UTC)),
        )
        after = _run(
            matcher,
            datetime(2022, 3, 13, 3, 30),
            _timeline(datetime(2022, 3, 13, 7, 30, tzinfo=UTC)),
        )
        assert len(before.matched) == 1
        assert len(after.matched) == 1
