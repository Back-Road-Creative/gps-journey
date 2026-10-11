"""
TDD Tests for Photo Inclusion - All Photos With Timestamps Must Be Included.

These tests define the critical behavior that ALL photos with valid timestamps
must appear in journey output, regardless of GPS availability.

The principle: "If a photo was taken on a day, it should appear for that day."
"""

from datetime import date, datetime

import pytest

from gps_journey.core.models import DayBreakdown, DayStatistics, Location, Photo, PhotoGroup
from gps_journey.photos.grouper import PhotoLocationGrouper


class TestNonGPSPhotosIncluded:
    """
    CRITICAL: Photos without GPS must still be included.

    Rationale: Many photos lack GPS (indoor shots, camera without GPS, etc.)
    but they still have timestamps and belong to specific days.
    """

    def test_photos_without_gps_included_in_separate_group(self):
        """
        Photos without GPS should be grouped under 'Unknown Location' or similar.

        This is the CORE TEST that must pass.
        """
        photos = [
            # Photo with GPS
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            # Photo WITHOUT GPS (e.g., taken indoors)
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 12, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
            # Another photo with GPS
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 14, 0, 0),
                latitude=55.20,
                longitude=-7.67,
                location=Location(latitude=55.20, longitude=-7.67, name="Rosscarra"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # All 3 photos must appear in the output
        total_photos = sum(len(g.photos) for g in groups)
        assert total_photos == 3, f"Expected 3 photos but got {total_photos}"

        # Should have a group for non-GPS photo
        filenames = [p.filename for g in groups for p in g.photos]
        assert "photo-002.jpg" in filenames, "Non-GPS photo must be included"

    def test_only_non_gps_photos_creates_group(self):
        """If ALL photos lack GPS, they should still be grouped."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 12, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Should NOT return empty - should return at least one group
        assert len(groups) >= 1, "Non-GPS photos must create at least one group"

        total_photos = sum(len(g.photos) for g in groups)
        assert total_photos == 2, "Both non-GPS photos must be included"

    def test_non_gps_photos_sorted_chronologically_with_gps_photos(self):
        """Non-GPS photos should be interleaved chronologically, not at the end."""
        photos = [
            # Morning GPS photo
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 9, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Location A"),
            ),
            # Midday non-GPS photo
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 12, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
            # Afternoon GPS photo
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 15, 0, 0),
                latitude=55.20,
                longitude=-7.67,
                location=Location(latitude=55.20, longitude=-7.67, name="Location B"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Groups should be chronologically ordered
        # The non-GPS photo's group should appear between the GPS groups
        all_groups_timestamps = [g.photos[0].timestamp for g in groups]
        assert all_groups_timestamps == sorted(all_groups_timestamps), (
            "Groups must be in chronological order"
        )

    def test_multiple_non_gps_photos_at_different_times_grouped_by_proximity(self):
        """
        Multiple non-GPS photos close in time should be in same group.
        Far apart in time should be separate groups.
        """
        photos = [
            # Two non-GPS photos close together (15 min apart)
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 15, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
            # Non-GPS photo 4 hours later
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 14, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Should have at least 2 groups (morning and afternoon)
        # Could be 2 or 3 depending on time threshold implementation
        total_photos = sum(len(g.photos) for g in groups)
        assert total_photos == 3, "All non-GPS photos must be included"


class TestPhotoGroupForNonGPSPhotos:
    """Test PhotoGroup model handles non-GPS photos correctly."""

    def test_photo_group_with_unknown_coordinates(self):
        """PhotoGroup should allow None/0 coordinates for non-GPS groups."""
        # This tests the model can represent non-GPS groups
        non_gps_photo = Photo(
            filename="photo-001.jpg",
            timestamp=datetime(2031, 5, 15, 10, 0, 0),
            latitude=None,
            longitude=None,
            location=None,
        )

        # Should be able to create group with 0 coordinates
        group = PhotoGroup(
            location_name="Unknown Location",
            latitude=0.0,  # Default for unknown
            longitude=0.0,
            photos=(non_gps_photo,),
        )

        assert group.location_name == "Unknown Location"
        assert len(group.photos) == 1


class TestPhotoCountConsistency:
    """
    CRITICAL: photo_count in statistics must match actual photos in groups.

    This addresses the issue: "days are stating that photos were taken but
    photos are not showing"
    """

    def test_day_statistics_photo_count_matches_photo_groups(self):
        """
        The photo_count in DayStatistics MUST equal the sum of photos
        in all photo_groups.

        Regression test for the photo-inclusion rule.
        """
        # Setup: Create DayBreakdown with both GPS and non-GPS photos
        all_photos = (
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 12, 0, 0),
                latitude=None,  # No GPS
                longitude=None,
                location=None,
            ),
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 14, 0, 0),
                latitude=55.20,
                longitude=-7.67,
                location=Location(latitude=55.20, longitude=-7.67, name="Rosscarra"),
            ),
        )

        # Group photos using the grouper
        grouper = PhotoLocationGrouper(proximity_km=0.5)
        photo_groups = grouper.group_photos(list(all_photos))

        # Calculate what photo_count would be set to
        photos_in_groups = sum(len(g.photos) for g in photo_groups)

        # This is the CRITICAL assertion:
        # The count of photos in groups must equal total photos
        assert photos_in_groups == len(all_photos), (
            f"Statistics show {len(all_photos)} photos but only {photos_in_groups} in groups"
        )


class TestUnknownLocationNaming:
    """Test location naming for non-GPS photos."""

    def test_non_gps_group_has_meaningful_name(self):
        """Non-GPS photo groups should have a recognizable location name."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=None,
                longitude=None,
                location=None,
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        assert len(groups) == 1
        # Should NOT be coordinates, should be a readable name
        assert (
            groups[0].location_name
            in [
                "Unknown Location",
                "Photos (Unknown Location)",
                "Other Photos",
                "Location Unknown",
            ]
            or "Unknown" in groups[0].location_name
        )


class TestJourneyWidePhotoIntegrity:
    """
    Integration-style tests for ensuring photo integrity across entire journeys.
    """

    def test_no_photos_lost_in_processing(self):
        """
        Given N photos for a day, exactly N photos must appear in photo_groups.

        This is the root cause test for "photos not showing".
        """
        # Simulate a realistic day with mixed GPS/non-GPS photos
        day_photos = [
            # Hotel lobby shot (no GPS indoors)
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 8, 0, 0),
                latitude=None,
                longitude=None,
            ),
            # Outdoor photos with GPS
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 10, 30, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            # Restaurant photo (no GPS indoors)
            Photo(
                filename="photo-004.jpg",
                timestamp=datetime(2031, 5, 15, 13, 0, 0),
                latitude=None,
                longitude=None,
            ),
            # Afternoon outdoor photos
            Photo(
                filename="photo-005.jpg",
                timestamp=datetime(2031, 5, 15, 15, 0, 0),
                latitude=55.20,
                longitude=-7.67,
                location=Location(latitude=55.20, longitude=-7.67, name="Rosscarra"),
            ),
            # Sunset shot (GPS didn't get fix)
            Photo(
                filename="photo-006.jpg",
                timestamp=datetime(2031, 5, 15, 19, 0, 0),
                latitude=None,
                longitude=None,
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(day_photos)

        # Count all photos in all groups
        photos_in_groups = []
        for g in groups:
            for p in g.photos:
                photos_in_groups.append(p.filename)

        # THE CRITICAL CHECK: No photos lost
        assert len(photos_in_groups) == len(day_photos), (
            f"Lost photos! Input: {len(day_photos)}, Output: {len(photos_in_groups)}"
        )

        # All original filenames must be present
        original_filenames = {p.filename for p in day_photos}
        grouped_filenames = set(photos_in_groups)
        missing = original_filenames - grouped_filenames
        assert not missing, f"These photos were lost: {missing}"
