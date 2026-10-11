"""
TDD Tests for Location Accuracy - Specific Location Names.

These tests ensure that GPS coordinates return specific, local place names
rather than distant city names. This is critical for accurate journey narratives.

Example issue: Coordinates in Westmere (County Tarrow) were returning "Kilvarra"
even though Kilvarra is ~15km away. The narrative incorrectly said
"We departed from Kilvarra" when the actual departure was from Westmere.
"""

from unittest.mock import MagicMock, patch

import pytest

from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient


class TestLocationSpecificity:
    """Tests ensuring departure locations are specific, not broad city names."""

    def test_city_district_takes_precedence_over_city(self):
        """
        Irish electoral districts (city_district) should be used over distant cities.

        In Ireland, Nominatim returns city_district for electoral divisions (EDs)
        like "Westmere ED", "Harbourview North ED", etc. These are more specific than
        the city field which may contain a distant town.
        """
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": None,
            "city_district": "Westmere ED",  # Irish electoral division
            "suburb": None,
            "town": None,
            "city": "Kilvarra",  # Distant city - should NOT be used
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should use city_district (cleaned), not city
        assert "Westmere" in location_str, f"Expected 'Westmere' in location, got: {location_str}"
        assert "Kilvarra" not in location_str, (
            f"Should not include distant city 'Kilvarra', got: {location_str}"
        )
        assert "County Tarrow" in location_str

    def test_locality_takes_precedence_over_city(self):
        """Locality should be returned instead of distant city."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": "Westmere",
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": "Kilvarra",
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        assert "Westmere" in location_str
        assert "Kilvarra" not in location_str

    def test_village_takes_precedence_over_all(self):
        """Village should be the top priority after POI name."""
        geo_data = {
            "latitude": 41.55,
            "longitude": -93.45,
            "village": "Eastport",
            "locality": "Westmere",
            "city_district": "Westmere ED",
            "suburb": None,
            "town": "Rosscarra",
            "city": "Kilvarra",
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should use village first
        assert location_str.startswith("Eastport"), (
            f"Expected to start with 'Eastport', got: {location_str}"
        )

    def test_poi_name_takes_highest_precedence(self):
        """POI name is used when the match is verified AT the fix (small
        match_distance_km)."""
        geo_data = {
            "latitude": 41.60,
            "longitude": -93.20,
            "village": "Mooreport",
            "locality": "Harbourview",
            "city_district": "Harbourview North ED",
            "suburb": None,
            "town": None,
            "city": "Kilvarra",
            "county": "County Tarrow",
            "poi_name": "Harbourview Head Lighthouse",
            "match_distance_km": 0.02,  # 20m — vehicle is AT the POI
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        assert location_str == "Harbourview Head Lighthouse"

    def test_poi_name_rejected_without_match_distance(self):
        """No match_distance_km (legacy cache entry) -> POI name is NOT
        trusted; falls through to the settlement hierarchy."""
        geo_data = {
            "latitude": 41.60,
            "longitude": -93.20,
            "village": "Mooreport",
            "county": "County Tarrow",
            "poi_name": "The Copper Lantern",
        }

        client = NominatimRoadsClient()
        assert client.format_location_string(geo_data) == "Mooreport, County Tarrow"

    def test_poi_name_rejected_when_match_far(self):
        """A POI matched beyond MAX_POI_MATCH_KM was only passed near — it
        must not title the location."""
        geo_data = {
            "latitude": 41.60,
            "longitude": -93.20,
            "village": "Mooreport",
            "county": "County Tarrow",
            "poi_name": "The Copper Lantern",
            "match_distance_km": 0.5,  # 500m away — drove past, not at
        }

        client = NominatimRoadsClient()
        assert client.format_location_string(geo_data) == "Mooreport, County Tarrow"

    def test_ed_suffix_cleaned_from_city_district(self):
        """Irish electoral division suffix 'ED' should be removed for readability."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": None,
            "city_district": "Westmere ED",
            "suburb": None,
            "town": None,
            "city": None,
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should clean up " ED" suffix
        assert " ED" not in location_str, f"Should remove ' ED' suffix, got: {location_str}"
        assert "Westmere" in location_str

    def test_fallback_to_coordinates_only_when_no_location_data(self):
        """Coordinates should only be used when no location data exists."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": None,
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": None,
            "county": None,
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should fall back to coordinates
        assert "41.5000" in location_str
        assert "-93.4000" in location_str

    def test_county_only_when_no_specific_location(self):
        """County should be returned when only county data exists."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": None,
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": None,
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        assert location_str == "County Tarrow"


class TestSpecificLocationCases:
    """Test specific known locations that previously had issues."""

    def test_westmere_area_not_kilvarra(self):
        """
        A village-level district must win over a distant city.

        If the departure area returned the larger city ~15 km away, a narrative
        would say "We departed from Kilvarra" when the departure was from
        Westmere.
        """
        # Simulated geocoding result for Westmere area
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": None,
            "locality": None,
            "city_district": "Westmere ED",  # This is what Nominatim returns
            "suburb": None,
            "town": None,
            "city": "Kilvarra",  # ~15km away - should NOT be used
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        assert "Kilvarra" not in location_str, (
            f"Westmere area should NOT return Kilvarra! Got: {location_str}"
        )

    def test_harbourview_north_not_kilvarra(self):
        """Harbourview North area should return Harbourview, not Kilvarra."""
        geo_data = {
            "latitude": 41.5400,
            "longitude": -93.2500,
            "village": None,
            "locality": None,
            "city_district": "Harbourview North ED",
            "suburb": None,
            "town": None,
            "city": "Kilvarra",
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        assert "Harbourview" in location_str
        assert "Kilvarra" not in location_str


class TestNarrativeLocationRequirements:
    """Tests for narrative-specific location requirements."""

    def test_location_string_has_no_coordinates(self):
        """Location strings should never contain raw coordinates unless no other data."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": "Eastport",
            "locality": None,
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": None,
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should not contain coordinate patterns when location data exists
        assert "55." not in location_str
        assert "-7." not in location_str

    def test_location_format_is_readable(self):
        """Location string should be human-readable format: 'Place, County'."""
        geo_data = {
            "latitude": 41.5000,
            "longitude": -93.4000,
            "village": "Eastport",
            "locality": None,
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": None,
            "county": "County Tarrow",
            "poi_name": None,
        }

        client = NominatimRoadsClient()
        location_str = client.format_location_string(geo_data)

        # Should be "Eastport, County Tarrow" format
        assert location_str == "Eastport, County Tarrow"
