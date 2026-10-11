"""OpenStreetMap Nominatim geocoding client."""

import logging
import time

from geopy.exc import GeocoderRateLimited, GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from gps_journey.core.models import Location
from gps_journey.geocoding.base import GeocodingError
from gps_journey.geocoding.cache import GeocodingCache

logger = logging.getLogger(__name__)


class NominatimClient:
    """
    OpenStreetMap Nominatim reverse geocoding client.

    Features:
    - Rate limiting (1 req/sec default per Nominatim usage policy)
    - Automatic caching with TTL
    - Retry logic for transient failures
    - Graceful fallback when service unavailable
    """

    def __init__(
        self,
        user_agent: str = "gps-journey/0.1.0",
        rate_limit: float = 1.0,
        cache: GeocodingCache | None = None,
        timeout: int = 10,
    ):
        """
        Initialize Nominatim client.

        Args:
            user_agent: User agent string (required by Nominatim)
            rate_limit: Requests per second (default: 1.0)
            cache: Optional geocoding cache
            timeout: Request timeout in seconds
        """
        self.user_agent = user_agent
        self.rate_limit = rate_limit
        self.cache = cache
        self.timeout = timeout
        self.last_request_time = 0.0

        self.geocoder = Nominatim(user_agent=user_agent, timeout=timeout)

        logger.info(
            f"Initialized Nominatim client (rate_limit={rate_limit}/s, "
            f"cache={'enabled' if cache else 'disabled'})"
        )

    def _rate_limit_wait(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        min_interval = 1.0 / self.rate_limit

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def reverse_geocode(self, latitude: float, longitude: float, retry: int = 3) -> Location:
        """
        Reverse geocode coordinates to place names.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            retry: Number of retry attempts for transient failures

        Returns:
            Location object with place name information

        Raises:
            GeocodingError: If geocoding fails after all retries
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get(latitude, longitude)
            if cached:
                logger.debug(f"Cache hit for {latitude:.4f},{longitude:.4f}")
                return cached

        # Rate limit
        self._rate_limit_wait()

        # Try geocoding with retries
        for attempt in range(retry):
            try:
                logger.debug(
                    f"Geocoding {latitude:.4f},{longitude:.4f} (attempt {attempt + 1}/{retry})"
                )

                result = self.geocoder.reverse(
                    (latitude, longitude),
                    language="en",
                    addressdetails=True,
                )

                if not result:
                    # No result found, return location with coords only
                    location = Location(latitude=latitude, longitude=longitude)
                    logger.warning(f"No geocoding result for {latitude:.4f},{longitude:.4f}")
                    return location

                # Parse address components
                address = result.raw.get("address", {})

                location = Location(
                    latitude=latitude,
                    longitude=longitude,
                    name=address.get("tourism")
                    or address.get("attraction")
                    or address.get("amenity"),
                    city=address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or address.get("hamlet"),
                    county=address.get("county"),
                    state=address.get("state") or address.get("province") or address.get("region"),
                    country=address.get("country"),
                    address=result.address if hasattr(result, "address") else None,
                )

                # Cache the result
                if self.cache:
                    self.cache.set(latitude, longitude, location)

                logger.info(f"Geocoded: {location}")
                return location

            except GeocoderTimedOut:
                logger.warning(f"Geocoding timeout (attempt {attempt + 1}/{retry})")
                if attempt < retry - 1:
                    time.sleep(2**attempt)  # Exponential backoff
                continue

            except GeocoderRateLimited as e:
                # Rate-limited (429) — DO NOT retry: retrying burns more
                # quota and makes the limit worse. Degrade to a coords-only
                # Location and never cache it, so a later run can refetch.
                # Must precede GeocoderServiceError, its parent class.
                logger.warning(
                    "Nominatim rate-limited at %.4f,%.4f: %s — returning "
                    "coords-only Location, NOT retrying.",
                    latitude,
                    longitude,
                    e,
                )
                return Location(latitude=latitude, longitude=longitude)

            except GeocoderServiceError as e:
                logger.error(f"Geocoding service error: {e}")
                if attempt < retry - 1:
                    time.sleep(2**attempt)
                continue

            except Exception as e:
                logger.error(f"Unexpected geocoding error: {e}")
                raise GeocodingError(f"Geocoding failed: {e}") from e

        # All retries exhausted
        raise GeocodingError(
            f"Geocoding failed after {retry} attempts for {latitude:.4f},{longitude:.4f}"
        )
