"""An empty GPS track accounts for every photo as unmatched."""

from datetime import datetime, timezone

import pytest

from gps_journey.photos.matcher import PhotoMatcher
from gps_journey.photos.models import Photo, PhotoMetadata

T0 = datetime(2022, 7, 1, 12, 0, tzinfo=timezone.utc)


def _photo(name: str) -> Photo:
    return Photo(
        id=name,
        filename=name,
        base_url="https://example.invalid/" + name,
        creation_time=T0,
        width=100,
        height=100,
        mime_type="image/jpeg",
    )


def _meta(photo: Photo) -> PhotoMetadata:
    return PhotoMetadata(photo_id=photo.id, timestamp=T0)


def test_empty_track_reports_every_photo_unmatched():
    photos = [_photo(f"IMG_{i}.jpg") for i in range(3)]
    report = PhotoMatcher().match_photos_with_report(photos, [_meta(p) for p in photos], [])
    assert report.unmatched == photos
    assert report.matched == []
    assert report.refused == []
    assert report.needs_clock_decision == []


def test_empty_track_with_mismatched_lengths_raises():
    photos = [_photo("a.jpg"), _photo("b.jpg")]
    with pytest.raises(ValueError, match="does not match"):
        PhotoMatcher().match_photos_with_report(photos, [_meta(photos[0])], [])
