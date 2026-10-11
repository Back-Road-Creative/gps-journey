"""Tests for the cache + rate-limit behavior of NominatimRoadsClient.

External API data must cache on
first fetch, and a 429 / rate-limit response must NEVER trigger a retry —
downstream code is expected to degrade gracefully using cached data and
the wrapper's empty-result fallback.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from geopy.exc import GeocoderRateLimited

from gps_journey.geocoding.cache import GeocodingCache
from gps_journey.geocoding.nominatim_roads import NominatimRoadsClient


def _make_raw_response(lat: float, lon: float) -> MagicMock:
    """Build a mock geopy Location-like result with a populated raw dict."""
    result = MagicMock()
    result.raw = {
        "lat": str(lat),
        "lon": str(lon),
        "class": "place",
        "type": "village",
        "importance": 0.3,
        "address": {
            "village": "Testville",
            "county": "Test County",
            "state": "South Carolina",
            "country": "United States",
        },
    }
    result.address = "Testville, Test County, SC, USA"
    return result


class TestDetailedCacheReadThrough:
    def test_cache_hit_skips_network(self, tmp_path):
        """A cached detailed dict must be returned without any geopy call."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        # Pre-populate the cache with a detailed dict
        cache.set_detailed(
            55.5,
            -7.5,
            {
                "latitude": 55.5,
                "longitude": -7.5,
                "village": "Prewritten",
                "county": "X County",
                "state": "South Carolina",
            },
        )

        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=1.0)
        # Replace the underlying geopy geocoder with a mock that would fail
        # if called — proving the cache hit skipped the network.
        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = AssertionError(
            "Network call made despite cached data"
        )

        result = client.reverse_geocode_detailed(55.5, -7.5)
        assert result["village"] == "Prewritten"
        # The mock reverse was never invoked
        client.geocoder.reverse.assert_not_called()

    def test_fresh_fetch_writes_to_cache(self, tmp_path):
        """On a cache miss, the fetched detailed dict must be written to the
        cache before returning to the caller — so the NEXT call hits cache."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)

        client.geocoder = MagicMock()
        client.geocoder.reverse.return_value = _make_raw_response(55.5, -7.5)

        # First call — cache miss, goes through network (mocked)
        result1 = client.reverse_geocode_detailed(55.5, -7.5)
        assert result1["village"] == "Testville"
        assert client.geocoder.reverse.call_count == 1

        # Second call at same coord — must hit cache, no additional reverse call
        result2 = client.reverse_geocode_detailed(55.5, -7.5)
        assert result2["village"] == "Testville"
        assert client.geocoder.reverse.call_count == 1  # still 1, not 2


class TestRateLimitNoRetry:
    def test_429_returns_empty_result_no_retry(self, tmp_path):
        """GeocoderRateLimited (429) must NOT trigger a retry. The client
        returns the empty-result dict and downstream code degrades."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)

        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = GeocoderRateLimited("Non-successful status code 429")

        result = client.reverse_geocode_detailed(55.5, -7.5, retry=3)

        # Must NOT retry — only one network attempt
        assert client.geocoder.reverse.call_count == 1
        # Must return an empty-result dict (not raise)
        assert isinstance(result, dict)
        assert result["village"] is None
        assert result["latitude"] == 55.5
        assert result["longitude"] == -7.5

    def test_429_does_not_poison_cache(self, tmp_path):
        """An empty result returned due to 429 must NOT be written to cache —
        otherwise the cache entry becomes permanently empty and the user can
        never refetch later after rate limit resets."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)

        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = GeocoderRateLimited("429")

        client.reverse_geocode_detailed(55.5, -7.5)

        # Cache must not contain a detailed entry for this coord
        cached = cache.get_detailed(55.5, -7.5)
        assert cached is None, "Empty result from rate-limited response leaked into cache"

    def test_timeout_still_retries(self, tmp_path):
        """Backward compat: plain timeouts (not rate limits) can still retry
        with exponential backoff. Only the 429 path is no-retry."""
        from geopy.exc import GeocoderTimedOut

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)

        # First two attempts time out, third succeeds
        responses = [
            GeocoderTimedOut("slow"),
            GeocoderTimedOut("slow"),
            _make_raw_response(55.5, -7.5),
        ]
        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = responses

        # Patch time.sleep to not actually wait between retries
        with patch("gps_journey.geocoding.nominatim_roads.time.sleep"):
            result = client.reverse_geocode_detailed(55.5, -7.5, retry=3)

        assert result["village"] == "Testville"
        assert client.geocoder.reverse.call_count == 3


class TestMatchDistance:
    def test_close_match_captures_coords_and_distance(self, tmp_path):
        """The matched object's coords + query distance are stored; a close
        match keeps its settlement fields."""
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        client.geocoder.reverse.return_value = _make_raw_response(55.5, -7.5)

        result = client.reverse_geocode_detailed(55.5, -7.5)

        assert result["match_latitude"] == 55.5
        assert result["match_longitude"] == -7.5
        assert result["match_distance_km"] == pytest.approx(0.0, abs=1e-6)
        assert result["village"] == "Testville"

    def test_far_match_rejects_settlement_fields(self, tmp_path):
        """A match >MAX_SETTLEMENT_MATCH_KM away is a catchment feature —
        village/town/hamlet/poi_name are rejected; county survives."""
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        raw = _make_raw_response(55.6, -7.5)  # ~11 km north of the query
        raw.raw["address"]["town"] = "Fartown"
        raw.raw["address"]["hamlet"] = "Farham"
        client.geocoder.reverse.return_value = raw

        result = client.reverse_geocode_detailed(55.5, -7.5)

        assert result["match_distance_km"] > 3.0
        assert result["village"] is None
        assert result["town"] is None
        assert result["hamlet"] is None
        assert result["poi_name"] is None
        assert result["county"] == "Test County"

    def test_missing_match_coords_yield_none_distance(self, tmp_path):
        """Raw responses without lat/lon (or unparsable) degrade to None —
        no rejection, no crash."""
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        raw = _make_raw_response(55.5, -7.5)
        del raw.raw["lat"], raw.raw["lon"]
        client.geocoder.reverse.return_value = raw

        result = client.reverse_geocode_detailed(55.5, -7.5)

        assert result["match_distance_km"] is None
        assert result["village"] == "Testville"


class TestBaseClientRateLimitNoRetry:
    def test_base_client_429_no_retry_no_cache(self, tmp_path):
        """Base NominatimClient must NOT retry a 429 (GeocoderRateLimited
        subclasses GeocoderServiceError, whose handler retries) — it degrades
        to a coords-only Location and never caches it."""
        from gps_journey.geocoding.nominatim import NominatimClient

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimClient(user_agent="test", cache=cache, rate_limit=100.0)
        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = GeocoderRateLimited("Non-successful status code 429")

        location = client.reverse_geocode(55.5, -7.5, retry=3)

        assert client.geocoder.reverse.call_count == 1  # no retry
        assert location.latitude == 55.5
        assert location.longitude == -7.5
        assert location.name is None
        assert cache.get(55.5, -7.5) is None  # not poisoned


class TestDetailedCachePersistence:
    def test_multiple_coords_share_one_cache_file(self, tmp_path):
        """Many unique coords accumulate in one cache file; no collisions."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)

        for i in range(5):
            cache.set_detailed(
                55.5 + i * 0.01,
                -7.5 + i * 0.01,
                {
                    "village": f"Place{i}",
                    "county": "X County",
                    "state": "South Carolina",
                },
            )

        # All 5 should be retrievable
        for i in range(5):
            cached = cache.get_detailed(55.5 + i * 0.01, -7.5 + i * 0.01)
            assert cached is not None
            assert cached["village"] == f"Place{i}"

        # Cache file should contain 5 entries under the 'detailed' key
        raw = json.loads((tmp_path / "cache.json").read_text())
        detailed_count = sum(1 for v in raw.values() if "detailed" in v)
        assert detailed_count == 5

    def test_detailed_cache_coexists_with_location_cache(self, tmp_path):
        """Location-based `set()` and detailed-based `set_detailed()` can
        store entries for the SAME coord without overwriting each other."""
        from gps_journey.core.models import Location

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)

        loc = Location(
            latitude=55.5,
            longitude=-7.5,
            name="LocOnly",
            city="X",
            county="Y",
            state="SC",
            country="USA",
        )
        cache.set(55.5, -7.5, loc)
        cache.set_detailed(55.5, -7.5, {"village": "DetailOnly", "county": "Y"})

        assert cache.get(55.5, -7.5) is not None
        cached_detailed = cache.get_detailed(55.5, -7.5)
        assert cached_detailed is not None
        assert cached_detailed["village"] == "DetailOnly"


class TestSettlementRankFields:
    """reverse_geocode_detailed must surface Nominatim's settlement-rank data
    (place_rank / address_rank / addresstype) so downstream settlement pickers
    can rank cities/towns over villages/hamlets (a larger town must outrank
    a smaller settlement when both are candidates)."""

    def test_raw_rank_fields_flow_into_detailed_dict(self):
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        result = _make_raw_response(55.5, -7.5)
        result.raw["place_rank"] = "19"  # Nominatim serves ranks as strings
        result.raw["address_rank"] = 19
        result.raw["addresstype"] = "village"
        client.geocoder.reverse.return_value = result

        detailed = client.reverse_geocode_detailed(55.5, -7.5)

        assert detailed["place_rank"] == 19
        assert detailed["address_rank"] == 19
        assert detailed["addresstype"] == "village"

    def test_missing_raw_rank_fields_default_none(self):
        """A raw response without the rank fields yields None, not KeyError."""
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        client.geocoder.reverse.return_value = _make_raw_response(55.5, -7.5)

        detailed = client.reverse_geocode_detailed(55.5, -7.5)

        assert detailed["place_rank"] is None
        assert detailed["address_rank"] is None
        assert detailed["addresstype"] is None

    def test_rank_fields_round_trip_through_cache(self, tmp_path):
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)
        client.geocoder = MagicMock()
        result = _make_raw_response(55.5, -7.5)
        result.raw["place_rank"] = 19
        result.raw["address_rank"] = 19
        result.raw["addresstype"] = "village"
        client.geocoder.reverse.return_value = result

        first = client.reverse_geocode_detailed(55.5, -7.5)
        second = client.reverse_geocode_detailed(55.5, -7.5)

        assert client.geocoder.reverse.call_count == 1  # second call hit cache
        assert first["place_rank"] == second["place_rank"] == 19
        assert first["address_rank"] == second["address_rank"] == 19
        assert first["addresstype"] == second["addresstype"] == "village"

    def test_legacy_cached_entry_returns_none_not_keyerror(self, tmp_path):
        """Cache entries written before the rank fields existed must
        deserialize with the new keys present as None — no KeyError."""
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        cache.set_detailed(
            55.5,
            -7.5,
            {"latitude": 55.5, "longitude": -7.5, "village": "Prewritten"},
        )

        client = NominatimRoadsClient(user_agent="test", cache=cache, rate_limit=100.0)
        client.geocoder = MagicMock()
        client.geocoder.reverse.side_effect = AssertionError(
            "Network call made despite cached data"
        )

        detailed = client.reverse_geocode_detailed(55.5, -7.5)

        assert detailed["village"] == "Prewritten"
        assert detailed["place_rank"] is None
        assert detailed["address_rank"] is None
        assert detailed["addresstype"] is None

    def test_empty_result_includes_rank_fields(self):
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()
        client.geocoder.reverse.return_value = None  # no match at coords

        detailed = client.reverse_geocode_detailed(55.5, -7.5)

        assert detailed["place_rank"] is None
        assert detailed["address_rank"] is None
        assert detailed["addresstype"] is None


class TestReverseGeocodeCarriesSettlementFields:
    """reverse_geocode() must surface town/village/hamlet on the Location so
    rural endpoints (no city) resolve to a real settlement, not just a
    county-joined `name`."""

    def test_rural_address_carries_town_village_hamlet(self, tmp_path):
        client = NominatimRoadsClient(user_agent="test", rate_limit=100.0)
        client.geocoder = MagicMock()

        result = MagicMock()
        result.raw = {
            "class": "place",
            "type": "village",
            "importance": 0.3,
            "address": {
                "town": "Cliffton",
                "village": "Ashby",
                "hamlet": "Drumcarra",
                "county": "County Tarrow",
                "state": "Northmarch",
                "country": "Ireland",
            },
        }
        result.address = "Ashby, County Tarrow, Ireland"
        client.geocoder.reverse.return_value = result

        loc = client.reverse_geocode(55.0, -8.3)

        assert loc.town == "Cliffton"
        assert loc.village == "Ashby"
        assert loc.hamlet == "Drumcarra"
        assert loc.city is None


class TestGetServesEitherNamespace:
    """`get()` must serve a Location from EITHER cache namespace: a fresh
    `location` sub-key (written by set()) is preferred, otherwise it
    reconstructs a Location from a fresh `detailed` sub-key (written by
    set_detailed() — the namespace the roads geocoder actually writes). A
    detailed-only entry is expired against its own `detailed_timestamp`, not
    the missing top-level `timestamp` (the old timestamp-0 garbage path).
    """

    def test_get_serves_location_from_detailed_namespace(self, tmp_path):
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        cache.set_detailed(
            55.0,
            -8.3,
            {
                "latitude": 55.0,
                "longitude": -8.3,
                "road": "N99",
                "village": "Ashby",
                "town": "Cliffton",
                "locality": "Ardbane",
                "hamlet": "Drumcarra",
                "county": "County Tarrow",
                "state": "Northmarch",
                "country": "Ireland",
                "full_address": "N99, Ashby, County Tarrow, Ireland",
            },
        )

        loc = cache.get(55.0, -8.3)

        assert loc is not None, "warm detailed cache must yield a Location, not None"
        assert loc.name == "Ashby"  # name prefers village
        assert loc.town == "Cliffton"
        assert loc.village == "Ashby"
        assert loc.hamlet == "Drumcarra"
        assert loc.locality == "Ardbane"
        assert loc.county == "County Tarrow"
        assert loc.state == "Northmarch"
        assert loc.country == "Ireland"
        assert loc.address == "N99, Ashby, County Tarrow, Ireland"

    def test_get_detailed_name_cascade(self, tmp_path):
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        # village absent -> town wins
        cache.set_detailed(1.0, 1.0, {"town": "T", "city": "C", "locality": "L"})
        assert cache.get(1.0, 1.0).name == "T"
        # village + town absent -> city wins
        cache.set_detailed(2.0, 2.0, {"city": "C", "locality": "L"})
        assert cache.get(2.0, 2.0).name == "C"
        # only locality -> locality last resort
        cache.set_detailed(3.0, 3.0, {"locality": "L"})
        assert cache.get(3.0, 3.0).name == "L"

    def test_get_detailed_honors_detailed_timestamp_expiry(self, tmp_path):
        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=1)
        cache.set_detailed(4.0, 5.0, {"village": "Old", "county": "X"})
        # Backdate the detailed_timestamp beyond the ttl (2 days > 1-day ttl).
        raw = json.loads((tmp_path / "cache.json").read_text())
        key = f"{4.0:.4f},{5.0:.4f}"
        raw[key]["detailed_timestamp"] = time.time() - 2 * 86400
        (tmp_path / "cache.json").write_text(json.dumps(raw))

        # Expiry honored via detailed_timestamp — NOT the timestamp-0 garbage
        # path that would previously mis-treat this as expired-and-empty.
        assert cache.get(4.0, 5.0) is None

    def test_get_still_serves_location_namespace(self, tmp_path):
        """Regression pin: the original set()+get() location path is unchanged."""
        from gps_journey.core.models import Location

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        loc = Location(
            latitude=6.0,
            longitude=7.0,
            name="LocName",
            city="Cty",
            town="Twn",
            village="Vlg",
            hamlet="Hml",
            county="Cnty",
            state="ST",
            country="US",
            address="Addr",
        )
        cache.set(6.0, 7.0, loc)

        got = cache.get(6.0, 7.0)
        assert got is not None
        assert got.name == "LocName"
        assert got.city == "Cty"
        assert got.town == "Twn"
        assert got.county == "Cnty"
        assert got.address == "Addr"

    def test_fresh_location_preferred_over_detailed(self, tmp_path):
        from gps_journey.core.models import Location

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=90)
        cache.set(8.0, 9.0, Location(latitude=8.0, longitude=9.0, name="FromLocation"))
        cache.set_detailed(8.0, 9.0, {"village": "FromDetailed"})

        # Both namespaces fresh -> location namespace wins.
        assert cache.get(8.0, 9.0).name == "FromLocation"

    def test_stale_location_falls_back_to_fresh_detailed(self, tmp_path):
        from gps_journey.core.models import Location

        cache = GeocodingCache(cache_path=tmp_path / "cache.json", ttl_days=1)
        cache.set(10.0, 11.0, Location(latitude=10.0, longitude=11.0, name="StaleLoc"))
        cache.set_detailed(10.0, 11.0, {"village": "FreshDetailed"})
        # Backdate ONLY the location timestamp; detailed stays fresh.
        raw = json.loads((tmp_path / "cache.json").read_text())
        key = f"{10.0:.4f},{11.0:.4f}"
        raw[key]["timestamp"] = time.time() - 2 * 86400
        (tmp_path / "cache.json").write_text(json.dumps(raw))

        got = cache.get(10.0, 11.0)
        assert got is not None
        assert got.name == "FreshDetailed"
