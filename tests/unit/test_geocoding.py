"""Unit tests for geocoding module."""

import json
import time
from pathlib import Path

import pytest

from gps_journey.core.models import Location
from gps_journey.geocoding.base import GeocodingError
from gps_journey.geocoding.cache import GeocodingCache


class MockGeocoder:
    """Mock geocoding provider for testing."""

    def reverse_geocode(self, latitude: float, longitude: float) -> Location:
        """Return a mock location."""
        return Location(
            latitude=latitude,
            longitude=longitude,
            name="Test Landmark",
            city="Test City",
            county="Test County",
            state="Test State",
            country="Test Country",
            address="123 Test St, Test City, Test Country",
        )


def test_geocoding_cache_set_and_get(tmp_path: Path):
    """Test storing and retrieving from cache."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file, ttl_days=90)

    location = Location(
        latitude=55.0,
        longitude=-7.0,
        city="Kilvarra",
        county="Tarrow",
        state="Northmarch",
        country="Ireland",
    )

    # Set cache
    cache.set(55.0, -7.0, location)

    # Get from cache
    cached = cache.get(55.0, -7.0)

    assert cached is not None
    assert cached.city == "Kilvarra"
    assert cached.county == "Tarrow"
    assert cached.country == "Ireland"


def test_geocoding_cache_round_trips_town_village_hamlet(tmp_path: Path):
    """A cache set->get must preserve town/village/hamlet — otherwise a cache
    hit silently drops the rural settlement fields the consumers read."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file, ttl_days=90)

    location = Location(
        latitude=55.0,
        longitude=-8.3,
        name="Ashby, County Tarrow",
        town="Cliffton",
        village="Ashby",
        hamlet="Drumcarra",
        county="County Tarrow",
        state="Northmarch",
        country="Ireland",
    )

    cache.set(55.0, -8.3, location)
    cached = cache.get(55.0, -8.3)

    assert cached is not None
    assert cached.town == "Cliffton"
    assert cached.village == "Ashby"
    assert cached.hamlet == "Drumcarra"


def test_geocoding_cache_miss(tmp_path: Path):
    """Test cache miss returns None."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file)

    result = cache.get(55.0, -7.0)
    assert result is None


def test_geocoding_cache_expiration(tmp_path: Path):
    """Test cache expiration with TTL."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file, ttl_days=0)  # Immediate expiration

    location = Location(
        latitude=55.0,
        longitude=-7.0,
        city="Test City",
    )

    cache.set(55.0, -7.0, location)

    # Manually modify cache to set old timestamp
    with open(cache_file) as f:
        cache_data = json.load(f)

    # Set timestamp to 2 days ago
    key = "55.0000,-7.0000"
    cache_data[key]["timestamp"] = time.time() - (2 * 86400)

    with open(cache_file, "w") as f:
        json.dump(cache_data, f)

    # Should return None (expired)
    result = cache.get(55.0, -7.0)
    assert result is None


def test_geocoding_cache_key_precision(tmp_path: Path):
    """Test cache key rounds coordinates to 4 decimal places."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file)

    location = Location(latitude=55.1234567, longitude=-7.9876543, city="Test")

    # Set with high precision coords
    cache.set(55.1234567, -7.9876543, location)

    # Get with exact same high precision coords - should match the rounded key
    cached = cache.get(55.1234567, -7.9876543)
    assert cached is not None
    assert cached.city == "Test"

    # Verify the key in cache file is rounded
    with open(cache_file) as f:
        cache_data = json.load(f)

    # Key should be rounded to 4 decimals
    assert "55.1235,-7.9877" in cache_data


def test_geocoding_cache_clear(tmp_path: Path):
    """Test clearing the cache."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file)

    location = Location(latitude=55.0, longitude=-7.0, city="Test")
    cache.set(55.0, -7.0, location)

    # Clear cache
    cache.clear()

    # Should be empty
    result = cache.get(55.0, -7.0)
    assert result is None


def test_geocoding_cache_stats(tmp_path: Path):
    """Test cache statistics."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file)

    # Add some entries
    for i in range(5):
        location = Location(latitude=55.0 + i, longitude=-7.0 + i, city=f"City{i}")
        cache.set(55.0 + i, -7.0 + i, location)

    stats = cache.stats()
    assert stats["total_entries"] == 5
    assert stats["active_entries"] == 5
    assert stats["file_size_kb"] > 0


def test_mock_geocoder():
    """Test mock geocoder for integration tests."""
    geocoder = MockGeocoder()
    location = geocoder.reverse_geocode(55.0, -7.0)

    assert location.latitude == 55.0
    assert location.longitude == -7.0
    assert location.city == "Test City"
    assert location.country == "Test Country"


def test_geocoding_with_cache(tmp_path: Path):
    """Test geocoding with caching integration."""
    from gps_journey.core.processor import JourneyProcessor

    cache_file = tmp_path / "geocode_cache.json"

    # Create processor with geocoding enabled
    processor = JourneyProcessor(
        geocoding_enabled=True,
        geocoding_provider=MockGeocoder(),
        geocoding_cache_path=cache_file,
    )

    # Process should work (though we need a real GPX file)
    # This test verifies the integration compiles correctly
    assert processor.geocoding_enabled is True
    assert processor.geocoder is not None
