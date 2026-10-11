"""Enhanced Nominatim client with road-level detail."""

import logging
import time

from geopy.distance import great_circle
from geopy.exc import GeocoderRateLimited, GeocoderTimedOut
from geopy.geocoders import Nominatim

from gps_journey.core.models import Location
from gps_journey.geocoding.base import GeocodingError
from gps_journey.geocoding.cache import GeocodingCache

logger = logging.getLogger(__name__)

# Detailed-dict keys added after the detailed cache format was first deployed.
# Legacy cached entries may lack them, so cache hits backfill them as None.
_OPTIONAL_DETAILED_FIELDS = ("place_rank", "address_rank", "addresstype")


def _to_int(value) -> int | None:
    """Coerce a raw Nominatim numeric field to int, or None if absent/junk."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# A reverse-geocode match whose OSM object sits farther than this from the
# query point is a catchment feature (e.g. a village node several km from a
# rural fix) — its settlement fields must not label the drive location.
MAX_SETTLEMENT_MATCH_KM = 3.0

# poi_name (a business/attraction) may title a location only when the matched
# feature is verified to be effectively AT the query point — not just nearby.
MAX_POI_MATCH_KM = 0.1


class NominatimRoadsClient:
    """
    Enhanced Nominatim client that extracts road names and detailed address info.

    Returns:
    - Road names (N99, R903, Main Street, etc.)
    - Town/village names
    - Landmarks and POIs
    - Detailed address components
    """

    def __init__(
        self,
        user_agent: str = "gps-journey/0.1.0",
        rate_limit: float = 1.0,
        cache: GeocodingCache | None = None,
        timeout: int = 10,
    ):
        """
        Initialize enhanced Nominatim client.

        Args:
            user_agent: User agent string (required by Nominatim)
            rate_limit: Requests per second
            cache: Optional geocoding cache
            timeout: Request timeout in seconds
        """
        self.user_agent = user_agent
        self.rate_limit = rate_limit
        self.cache = cache
        self.timeout = timeout
        self.last_request_time = 0.0

        self.geocoder = Nominatim(user_agent=user_agent, timeout=timeout)

        logger.info(f"Initialized Nominatim Roads client (rate={rate_limit}/s)")

    def _rate_limit_wait(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        min_interval = 1.0 / self.rate_limit

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def reverse_geocode_detailed(self, latitude: float, longitude: float, retry: int = 3) -> dict:
        """
        Reverse geocode with detailed address components including roads.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            retry: Number of retry attempts

        Returns:
            Dictionary with detailed address components:
            {
                "road": "N99" or "Main Street",
                "village": "Eastport",
                "town": "Kilvarra",
                "county": "County Tarrow",
                "state": "Northmarch",
                "country": "Ireland",
                "postcode": "X00 ...",
                "poi": "The Copper Lantern" (if at a landmark),
                "full_address": "N99, Eastport, County Tarrow, Ireland"
            }

        Raises:
            GeocodingError: If geocoding fails
        """
        # Check the detailed-dict cache first (skips both network and rate limit).
        if self.cache:
            cached_detailed = self.cache.get_detailed(latitude, longitude)
            if isinstance(cached_detailed, dict):
                logger.debug(f"Detailed cache hit for {latitude:.4f},{longitude:.4f}")
                # Legacy entries predate the settlement-rank fields; serve
                # them with the new keys present as None (never KeyError).
                for field in _OPTIONAL_DETAILED_FIELDS:
                    cached_detailed.setdefault(field, None)
                return cached_detailed

        # Rate limit
        self._rate_limit_wait()

        # Try geocoding with retries
        for attempt in range(retry):
            try:
                logger.debug(f"Geocoding {latitude:.4f},{longitude:.4f} with addressdetails")

                result = self.geocoder.reverse(
                    (latitude, longitude),
                    language="en",
                    addressdetails=True,
                    zoom=18,  # Higher zoom for more detail
                )

                if not result:
                    return self._empty_result(latitude, longitude)

                # Extract all address components
                address = result.raw.get("address", {})

                # The matched OSM object's own coordinates (raw lat/lon are
                # strings). Query-to-match distance is the key trust signal:
                # a match several km away is a far-away catchment feature,
                # not where the vehicle actually is.
                try:
                    match_lat: float | None = float(result.raw["lat"])
                    match_lon: float | None = float(result.raw["lon"])
                    match_distance_km: float | None = great_circle(
                        (latitude, longitude), (match_lat, match_lon)
                    ).km
                except (KeyError, TypeError, ValueError):
                    match_lat = None
                    match_lon = None
                    match_distance_km = None

                # Nominatim exposes an OSM feature "class" (e.g. "place",
                # "highway") and an "importance" score (0.0-1.0) at the top
                # level of the raw response. Downstream ranking (endpoint
                # selection) needs both to prefer recognizable cities over
                # tiny villages.
                raw_importance = result.raw.get("importance")
                try:
                    importance = float(raw_importance) if raw_importance is not None else None
                except (TypeError, ValueError):
                    importance = None

                # Keep village and hamlet SEPARATE (don't conflate) so
                # downstream consumers can apply different reliability rules:
                # village entries from OSM are usually real populated places;
                # hamlet entries are frequently rural postal designations
                # that need blacklist / match-type filtering before being
                # trusted as a drive location.
                detailed = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "road": address.get("road") or address.get("pedestrian") or address.get("path"),
                    "village": address.get("village"),
                    "hamlet": address.get("hamlet"),
                    "locality": address.get("locality")
                    or address.get("isolated_dwelling")
                    or address.get("neighbourhood"),
                    "city_district": address.get(
                        "city_district"
                    ),  # Irish electoral districts/townlands
                    "suburb": address.get("suburb"),
                    "town": address.get("town"),
                    "city": address.get("city"),
                    "county": address.get("county"),
                    "state": address.get("state"),
                    "country": address.get("country"),
                    "postcode": address.get("postcode"),
                    "poi": address.get("tourism")
                    or address.get("amenity")
                    or address.get("attraction")
                    or address.get("leisure")
                    or address.get("shop"),
                    "poi_name": result.raw.get("name")
                    if result.raw.get("class") in ["tourism", "amenity"]
                    else None,
                    # `place_class` is the top-level OSM feature class
                    # ("place", "highway", "amenity", etc). `match_type` is
                    # the more specific type ("house", "hamlet", "village",
                    # "trunk", etc.) and is the key reliability signal —
                    # a type="house" match with only an address.hamlet means
                    # the match is a specific building in a rural postal
                    # area, not a real place entity.
                    "place_class": result.raw.get("class"),
                    "match_type": result.raw.get("type"),
                    "importance": importance,
                    # Nominatim settlement-rank data: place_rank/address_rank
                    # are coarse OSM rank tiers (city=16, town=18, village=19,
                    # hamlet=20 — lower is more significant); addresstype
                    # names the address bucket the match fell into ("town",
                    # "hamlet", ...). Downstream settlement pickers use these
                    # to rank towns over hamlets.
                    "place_rank": _to_int(result.raw.get("place_rank")),
                    "address_rank": _to_int(result.raw.get("address_rank")),
                    "addresstype": result.raw.get("addresstype"),
                    "match_latitude": match_lat,
                    "match_longitude": match_lon,
                    "match_distance_km": match_distance_km,
                    "full_address": result.address if hasattr(result, "address") else None,
                }

                # Reject settlement/POI labels from far-away matches AT THE
                # SOURCE (before caching) so no consumer can burn a catchment
                # village or passed-by business into titles/narratives.
                # Coarse admin fields (county/state/country) stay — they are
                # valid at any match distance.
                if match_distance_km is not None and match_distance_km > MAX_SETTLEMENT_MATCH_KM:
                    logger.debug(
                        f"Match {match_distance_km:.1f}km from query point — "
                        f"rejecting settlement fields (village/town/hamlet/poi_name)"
                    )
                    detailed["village"] = None
                    detailed["town"] = None
                    detailed["hamlet"] = None
                    detailed["poi_name"] = None

                logger.debug(
                    f"Geocoded: {detailed['poi_name'] or detailed['road'] or detailed['village'] or detailed['county']}"
                )

                # Store the fresh detailed dict in the cache so future calls
                # at these exact coords skip both the network hop and the
                # 1/sec rate limit.
                if self.cache:
                    try:
                        self.cache.set_detailed(latitude, longitude, detailed)
                    except Exception as cache_err:
                        logger.debug(f"Detailed cache write failed: {cache_err}")

                return detailed

            except GeocoderRateLimited as e:
                # Rate-limited — DO NOT retry.
                # Retrying burns more quota and makes the limit worse. Return
                # an empty result so downstream code degrades gracefully to
                # cached / county / state fallbacks. The operator must wait
                # for the rate limit to reset before rerunning.
                logger.warning(
                    "Nominatim rate-limited at %.4f,%.4f: %s — returning "
                    "empty result, NOT retrying. Cached results still usable.",
                    latitude,
                    longitude,
                    e,
                )
                return self._empty_result(latitude, longitude)

            except GeocoderTimedOut:
                if attempt < retry - 1:
                    time.sleep(2**attempt)
                continue

            except Exception:
                if attempt < retry - 1:
                    time.sleep(2**attempt)
                continue

        raise GeocodingError(f"Geocoding failed after {retry} attempts")

    def _empty_result(self, latitude: float, longitude: float) -> dict:
        """Return empty result structure."""
        return {
            "latitude": latitude,
            "longitude": longitude,
            "road": None,
            "village": None,
            "hamlet": None,
            "locality": None,
            "city_district": None,
            "suburb": None,
            "town": None,
            "city": None,
            "county": None,
            "state": None,
            "country": None,
            "postcode": None,
            "poi": None,
            "poi_name": None,
            "place_class": None,
            "match_type": None,
            "importance": None,
            "place_rank": None,
            "address_rank": None,
            "addresstype": None,
            "match_latitude": None,
            "match_longitude": None,
            "match_distance_km": None,
            "full_address": None,
        }

    def format_location_string(self, geo_data: dict) -> str:
        """
        Format geocoding result into a readable location string.

        Priority order (most specific first):
        POI name > Village > Locality > City District > Suburb > Town > City > County > Coordinates

        POI names (businesses/attractions) require positive distance
        verification: used only when match_distance_km shows the fix is
        effectively AT the POI (<= MAX_POI_MATCH_KM). Legacy cache entries
        without the distance fall through to the settlement hierarchy rather
        than trusting a business the drive may only have passed near.

        Note: city_district often contains Irish electoral divisions (EDs) like "Westmere ED"
        which are more specific than distant city names. The " ED" suffix is cleaned for readability.
        """
        match_km = geo_data.get("match_distance_km")
        if geo_data.get("poi_name") and match_km is not None and match_km <= MAX_POI_MATCH_KM:
            return geo_data["poi_name"]

        parts = []

        # Prioritize smallest/most specific location first
        # CRITICAL: city_district (Irish electoral divisions) must come before city
        # to avoid returning distant cities like "Kilvarra" when in "Westmere"
        specific_location = None
        if geo_data.get("village"):
            specific_location = geo_data["village"]
        elif geo_data.get("locality"):
            specific_location = geo_data["locality"]
        elif geo_data.get("city_district"):
            # Clean up " ED" suffix from Irish electoral divisions
            specific_location = geo_data["city_district"]
            if specific_location.endswith(" ED"):
                specific_location = specific_location[:-3]
        elif geo_data.get("suburb"):
            specific_location = geo_data["suburb"]
        elif geo_data.get("town"):
            specific_location = geo_data["town"]
        elif geo_data.get("city"):
            specific_location = geo_data["city"]

        if specific_location:
            parts.append(specific_location)

        if geo_data.get("county"):
            parts.append(geo_data["county"])

        if parts:
            return ", ".join(parts)

        # Fallback to coordinates
        return f"{geo_data['latitude']:.4f}°, {geo_data['longitude']:.4f}°"

    def reverse_geocode(self, latitude: float, longitude: float) -> Location:
        """
        Reverse geocode coordinates using TDD-tested location hierarchy.

        Wraps reverse_geocode_detailed() and converts to Location object.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees

        Returns:
            Location object with TDD-tested specific location names

        Raises:
            GeocodingError: If geocoding fails
        """
        geo_data = self.reverse_geocode_detailed(latitude, longitude)

        # Use format_location_string for the name (TDD-tested hierarchy)
        location_name = self.format_location_string(geo_data)

        return Location(
            latitude=latitude,
            longitude=longitude,
            name=location_name,
            locality=geo_data.get("locality"),
            suburb=geo_data.get("suburb"),
            city=geo_data.get("city"),
            # Keep town/village/hamlet SEPARATE (see reverse_geocode_detailed):
            # village entries are usually real places, hamlet entries are often
            # rural postal designations — consumers apply different trust rules.
            town=geo_data.get("town"),
            village=geo_data.get("village"),
            hamlet=geo_data.get("hamlet"),
            county=geo_data.get("county"),
            state=geo_data.get("state"),
            country=geo_data.get("country"),
            address=geo_data.get("full_address"),
        )
