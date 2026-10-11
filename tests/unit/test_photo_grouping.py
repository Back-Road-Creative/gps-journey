"""
TDD Tests for Photo Location Grouping.

These tests define the expected behavior of PhotoLocationGrouper
before implementation.
"""

from datetime import datetime

import pytest

from gps_journey.core.models import Location, Photo, PhotoGroup
from gps_journey.photos.grouper import PhotoLocationGrouper


class TestPhotoLocationGrouper:
    """Test PhotoLocationGrouper class."""

    def test_single_location_all_photos_grouped(self):
        """Test photos at same location are grouped together."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.1234,
                longitude=-7.5678,
                location=Location(latitude=55.1234, longitude=-7.5678, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 5, 0),
                latitude=55.1235,  # Very close (within 0.5km)
                longitude=-7.5679,
                location=Location(latitude=55.1235, longitude=-7.5679, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 10, 10, 0),
                latitude=55.1236,  # Very close
                longitude=-7.5680,
                location=Location(latitude=55.1236, longitude=-7.5680, name="Harbourview Head"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # All should be in one group
        assert len(groups) == 1
        assert len(groups[0].photos) == 3
        assert groups[0].location_name == "Harbourview Head"

    def test_multiple_locations_separate_groups(self):
        """Test photos at different locations are grouped separately."""
        photos = [
            # Morning at Harbourview Head
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 5, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            # Afternoon at Rosscarra (20km away)
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 14, 0, 0),
                latitude=55.20,
                longitude=-7.67,
                location=Location(latitude=55.20, longitude=-7.67, name="Rosscarra"),
            ),
            # Evening at Westmere (15km from Rosscarra)
            Photo(
                filename="photo-004.jpg",
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                latitude=55.15,
                longitude=-7.80,
                location=Location(latitude=55.15, longitude=-7.80, name="Westmere"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Should have 3 separate groups
        assert len(groups) == 3
        assert groups[0].location_name == "Harbourview Head"
        assert len(groups[0].photos) == 2
        assert groups[1].location_name == "Rosscarra"
        assert len(groups[1].photos) == 1
        assert groups[2].location_name == "Westmere"
        assert len(groups[2].photos) == 1

    def test_chronological_ordering_between_groups(self):
        """Test groups are ordered chronologically by first photo time."""
        photos = [
            # Evening photo (should be group 2)
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 17, 0, 0),
                latitude=55.15,
                longitude=-7.80,
                location=Location(latitude=55.15, longitude=-7.80, name="Westmere"),
            ),
            # Morning photo (should be group 1)
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            # Afternoon photo (should be group 2 - back at Westmere)
            Photo(
                filename="photo-004.jpg",
                timestamp=datetime(2031, 5, 15, 18, 0, 0),
                latitude=55.15,
                longitude=-7.80,
                location=Location(latitude=55.15, longitude=-7.80, name="Westmere"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Groups should be in chronological order
        assert len(groups) == 2
        assert groups[0].location_name == "Harbourview Head"  # Morning first
        assert groups[0].photos[0].timestamp.hour == 10
        assert groups[1].location_name == "Westmere"  # Afternoon/evening second
        assert groups[1].photos[0].timestamp.hour == 17

    def test_chronological_ordering_within_groups(self):
        """Test photos within a group are sorted chronologically."""
        photos = [
            # Photos taken at same location but out of order
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 10, 20, 0),  # Third
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),  # First
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 10, 0),  # Second
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        assert len(groups) == 1
        # Photos should be sorted by timestamp
        assert groups[0].photos[0].filename == "photo-001.jpg"  # 10:00
        assert groups[0].photos[1].filename == "photo-002.jpg"  # 10:10
        assert groups[0].photos[2].filename == "photo-003.jpg"  # 10:20

    def test_photos_without_gps_included_in_unknown_location(self):
        """Test photos without GPS are included in 'Unknown Location' group."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 5, 0),
                latitude=None,  # No GPS
                longitude=None,
                location=None,
            ),
            Photo(
                filename="photo-003.jpg",
                timestamp=datetime(2031, 5, 15, 10, 10, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63, name="Harbourview Head"),
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # All 3 photos must be included
        total_photos = sum(len(g.photos) for g in groups)
        assert total_photos == 3

        # Non-GPS photo should be in "Unknown Location" group
        non_gps_groups = [g for g in groups if g.location_name == "Unknown Location"]
        assert len(non_gps_groups) == 1
        assert non_gps_groups[0].photos[0].filename == "photo-002.jpg"

    def test_location_name_assignment(self):
        """Test location name is assigned from first photo's location."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(
                    latitude=55.27,
                    longitude=-7.63,
                    name="Harbourview Head Lighthouse",
                    locality="Harbourview North",
                    county="County Tarrow",
                ),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 5, 0),
                latitude=55.27,
                longitude=-7.63,
                location=Location(latitude=55.27, longitude=-7.63),  # Less detail
            ),
        ]

        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos(photos)

        # Should use first photo's location name
        assert (
            groups[0].location_name
            == "Harbourview Head Lighthouse, Harbourview North, County Tarrow"
        )

    def test_empty_photos_list(self):
        """Test empty photos list returns empty groups."""
        grouper = PhotoLocationGrouper(proximity_km=0.5)
        groups = grouper.group_photos([])

        assert len(groups) == 0

    def test_custom_proximity_threshold(self):
        """Test custom proximity threshold works correctly."""
        photos = [
            Photo(
                filename="photo-001.jpg",
                timestamp=datetime(2031, 5, 15, 10, 0, 0),
                latitude=55.0,
                longitude=-7.0,
                location=Location(latitude=55.0, longitude=-7.0, name="Location A"),
            ),
            Photo(
                filename="photo-002.jpg",
                timestamp=datetime(2031, 5, 15, 10, 5, 0),
                latitude=55.01,  # ~1km away
                longitude=-7.0,
                location=Location(latitude=55.01, longitude=-7.0, name="Location B"),
            ),
        ]

        # With 0.5km threshold: should be 2 groups
        grouper_tight = PhotoLocationGrouper(proximity_km=0.5)
        groups_tight = grouper_tight.group_photos(photos)
        assert len(groups_tight) == 2

        # With 2km threshold: should be 1 group
        grouper_loose = PhotoLocationGrouper(proximity_km=2.0)
        groups_loose = grouper_loose.group_photos(photos)
        assert len(groups_loose) == 1
