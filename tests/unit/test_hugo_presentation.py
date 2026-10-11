"""TDD tests for Hugo presentation layer - these tests MUST FAIL initially.

These tests prove the current issues with:
1. Featured image paths not matching actual files
2. Missing gallery_path for photo display
3. Poor narrative quality (0 km, admin codes, parking lots)
"""

from datetime import datetime

import pytest

from gps_journey.hugo.generator import HugoGenerator
from gps_journey.narrative.simple_generator import SimpleNarrativeGenerator


class TestFeaturedImagePaths:
    """Test that featured image paths match actual file naming convention."""

    def test_featured_image_uses_journey_id_when_provided(self):
        """Featured image should use provided journey_id, not slugified title.

        The generator should accept a journey_id parameter and use it for
        the featured_image path.
        """
        from datetime import datetime

        from gps_journey.core.models import Journey, JourneyStatistics, Location

        generator = HugoGenerator()

        journey = Journey(
            title="Sample Road Trip - June 2030",
            start_date=datetime(2030, 6, 1),
            end_date=datetime(2030, 6, 15),
            start_location=Location(
                latitude=53.0, longitude=-8.0, city="Ennerby", country="Ireland"
            ),
            end_location=Location(
                latitude=53.0, longitude=-8.0, city="Fairhaven", country="Ireland"
            ),
            statistics=JourneyStatistics(
                total_distance_km=500,
                total_distance_miles=310,
                total_elevation_gain_m=1000,
                total_elevation_loss_m=950,
                moving_time_seconds=36000,
                stopped_time_seconds=7200,
                average_speed_kmh=25,
                max_speed_kmh=90,
                min_elevation_m=0,
                max_elevation_m=300,
            ),
        )

        frontmatter = generator._build_frontmatter(
            journey,
            title="Sample Road Trip - June 2030",
            featured_image_slug="sample-trip-2030-06",
        )

        assert frontmatter["featured_image"] == "images/featured/sample-trip-2030-06.jpg", (
            f"Featured image should use provided journey_id, got '{frontmatter['featured_image']}'"
        )

    def test_featured_image_no_triple_dashes_when_using_journey_id(self):
        """When using journey_id, featured image path should be clean."""
        from datetime import datetime

        from gps_journey.core.models import Journey, JourneyStatistics, Location

        generator = HugoGenerator()

        journey = Journey(
            title="Sample Road Trip - May 2031",
            start_date=datetime(2031, 5, 15),
            end_date=datetime(2031, 5, 27),
            start_location=Location(
                latitude=53.0, longitude=-8.0, city="Dublin", country="Ireland"
            ),
            end_location=Location(latitude=53.0, longitude=-8.0, city="Dublin", country="Ireland"),
            statistics=JourneyStatistics(
                total_distance_km=2000,
                total_distance_miles=1243,
                total_elevation_gain_m=15000,
                total_elevation_loss_m=14500,
                moving_time_seconds=360000,
                stopped_time_seconds=72000,
                average_speed_kmh=40,
                max_speed_kmh=120,
                min_elevation_m=0,
                max_elevation_m=500,
            ),
        )

        frontmatter = generator._build_frontmatter(
            journey,
            title="Sample Road Trip - May 2031",
            featured_image_slug="sample-trip-2031-05",
        )

        assert "---" not in frontmatter["featured_image"], (
            f"Featured image path contains ugly triple-dash: '{frontmatter['featured_image']}'"
        )

    @pytest.mark.parametrize(
        "title,journey_id",
        [
            ("Sample Road Trip - June 2030", "sample-trip-2030-06"),
            ("Sample Road Trip - May 2031", "sample-trip-2031-05"),
            ("Sample Road Trip - Fall 2031", "sample-trip-2031-fall"),
            ("Sample Road Trip - January 2030", "sample-trip-2030-01"),
            ("Lakes Road Trip - 2030", "lakes-2030"),
            ("Coast Road Trip - 2031", "coast-2031"),
        ],
    )
    def test_featured_image_matches_actual_files_with_journey_id(self, title, journey_id):
        """When journey_id is provided, featured_image path should match actual files."""
        from datetime import datetime

        from gps_journey.core.models import Journey, JourneyStatistics, Location

        generator = HugoGenerator()

        journey = Journey(
            title=title,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
            start_location=Location(
                latitude=53.0, longitude=-8.0, city="Dublin", country="Ireland"
            ),
            end_location=Location(
                latitude=53.0, longitude=-8.0, city="Fairhaven", country="Ireland"
            ),
            statistics=JourneyStatistics(
                total_distance_km=500,
                total_distance_miles=310,
                total_elevation_gain_m=1000,
                total_elevation_loss_m=950,
                moving_time_seconds=36000,
                stopped_time_seconds=7200,
                average_speed_kmh=25,
                max_speed_kmh=90,
                min_elevation_m=0,
                max_elevation_m=300,
            ),
        )

        frontmatter = generator._build_frontmatter(
            journey,
            title=title,
            featured_image_slug=journey_id,
        )

        expected_path = f"images/featured/{journey_id}.jpg"
        assert frontmatter["featured_image"] == expected_path, (
            f"Featured image should be '{expected_path}', but got '{frontmatter['featured_image']}'"
        )


class TestGalleryPath:
    """Test that gallery_path is included in frontmatter for photo display."""

    def test_frontmatter_includes_gallery_path_when_provided(self):
        """Frontmatter must include gallery_path for template photo rendering.

        The site template reads the gallery_path parameter.
        Without this field, photos show broken links.
        """
        # Import and check the generator's frontmatter output
        generator = HugoGenerator()

        # Create minimal journey data for testing
        from datetime import datetime

        from gps_journey.core.models import Journey, JourneyStatistics, Location

        journey = Journey(
            title="Test Journey",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
            start_location=Location(
                latitude=53.0, longitude=-8.0, city="Test City", country="Ireland"
            ),
            end_location=Location(
                latitude=53.0, longitude=-8.0, city="Test City", country="Ireland"
            ),
            statistics=JourneyStatistics(
                total_distance_km=100,
                total_distance_miles=62,
                total_elevation_gain_m=500,
                total_elevation_loss_m=400,
                moving_time_seconds=18000,
                stopped_time_seconds=3600,
                average_speed_kmh=20,
                max_speed_kmh=80,
                min_elevation_m=0,
                max_elevation_m=500,
            ),
        )

        frontmatter = generator._build_frontmatter(
            journey,
            "Test Journey",
            gallery_path="images/journeys/test-journey",
        )

        assert "gallery_path" in frontmatter, (
            "Frontmatter must include 'gallery_path' for photo display. "
            "Without it, the template cannot render photo links. "
            "Expected: gallery_path: images/journeys/test-journey"
        )
        assert frontmatter["gallery_path"] == "images/journeys/test-journey", (
            f"gallery_path should be 'images/journeys/test-journey', "
            f"got '{frontmatter['gallery_path']}'"
        )


class TestNarrativeQuality:
    """Test that narratives don't contain known bad patterns."""

    def test_no_zero_distance_shown_for_photo_journeys(self):
        """Photo-based journeys shouldn't show 'covering 0 km (0 miles)'.

        This is meaningless information that confuses readers.

        This test MUST FAIL until the narrative generator handles 0 distance.
        """
        generator = SimpleNarrativeGenerator()

        # Photo-based journey with 0 distance
        narrative = generator.generate_day_narrative(
            day_number=2,
            date=datetime(2030, 6, 2),
            start_location="Hartigan's",
            end_location="Glenroe, County Brenmore",
            distance_km=0.0,  # Photo journey - no GPS track
            duration_hours=13.7,
            elevation_gain_m=0,
            towns_visited=["Hartigan's", "Glenroe, County Brenmore"],
            photo_count=46,
        )

        assert "0 km (0 miles)" not in narrative, (
            f"Narrative shows meaningless '0 km (0 miles)': {narrative}. "
            "Photo-based journeys should omit distance or say 'Photo journey'."
        )

    def test_no_administrative_codes_in_locations(self):
        """Location names should not include administrative codes like 'No. 3 Urban'."""
        from gps_journey.narrative.simple_generator import filter_locations

        bad_names = [
            "Ennerby No. 3 Urban",
            "Ennerby No. 4 Urban",
            "Carrowdale Urban, County Ashmoor",
        ]

        # These patterns should be filtered out
        filtered = filter_locations(bad_names)

        assert len(filtered) == 0, f"Admin codes should be filtered out. Got: {filtered}"

    def test_no_parking_lot_names_in_narrative(self):
        """Narratives should not include parking lot names as destinations."""
        generator = SimpleNarrativeGenerator()

        narrative = generator.generate_day_narrative(
            day_number=2,
            date=datetime(2030, 6, 2),
            start_location="Ennerby",
            end_location="Glenroe",
            distance_km=50.0,
            duration_hours=5.0,
            elevation_gain_m=300,
            towns_visited=["Ennerby", "Abbey Street Car Park", "Glenroe"],
            photo_count=20,
        )

        assert "Car Park" not in narrative, (
            f"Narrative includes parking lot name: {narrative}. "
            "Parking lots should be filtered from location lists."
        )

    def test_no_lazy_other_locations_phrasing(self):
        """Narratives should list actual locations, not 'and X other locations'."""
        generator = SimpleNarrativeGenerator()

        narrative = generator.generate_day_narrative(
            day_number=2,
            date=datetime(2030, 6, 2),
            start_location="Ennerby",
            end_location="Fairhaven",
            distance_km=100.0,
            duration_hours=8.0,
            elevation_gain_m=500,
            towns_visited=["Ennerby", "Gortmore", "Kilmara", "Oranvale", "Fairhaven"],
            photo_count=30,
        )

        assert "other location" not in narrative.lower(), (
            f"Narrative uses lazy 'other locations' phrasing: {narrative}. "
            "Should list actual location names or summarize the route meaningfully."
        )


class TestLocationFiltering:
    """Test that locations are properly filtered before narrative generation."""

    BAD_LOCATION_PATTERNS = [  # noqa: RUF012
        # Administrative codes
        r"No\. \d+ Urban",
        r"No\. \d+ Rural",
        r"Urban, County",
        r"Rural, County",
        # Parking
        r"Car Park",
        r"Parking",
        # Generic POIs that shouldn't be primary locations
        r"^(Tesco|Lidl|Aldi|SuperValu)",
        r"^(Centra|Spar|Maxol)",
        r"^(BP|Shell|Circle K)",
    ]

    def test_filter_excludes_admin_codes(self):
        """Admin codes like 'Ennerby No. 3 Urban' should be filtered."""
        import re

        test_locations = [
            "Ennerby No. 3 Urban, County Brenmore",
            "Ennerby No. 4 Urban, County Brenmore",
            "Carrowdale Urban, County Ashmoor",
        ]

        for loc in test_locations:
            is_bad = any(re.search(pattern, loc) for pattern in self.BAD_LOCATION_PATTERNS)
            assert is_bad, f"'{loc}' should match a bad pattern and be filtered"

    def test_filter_excludes_parking(self):
        """Parking locations should be filtered."""
        import re

        test_locations = [
            "Abbey Street Car Park",
            "Shopping Centre Parking",
        ]

        for loc in test_locations:
            is_bad = any(re.search(pattern, loc) for pattern in self.BAD_LOCATION_PATTERNS)
            assert is_bad, f"'{loc}' should match a bad pattern and be filtered"
