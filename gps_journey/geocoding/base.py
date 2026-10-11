"""Base geocoding provider interface."""

from typing import Protocol

from gps_journey.core.models import Location


class GeocodingProvider(Protocol):
    """
    Abstract interface for geocoding providers.

    All geocoding implementations must follow this protocol.
    """

    def reverse_geocode(self, latitude: float, longitude: float) -> Location:
        """
        Convert coordinates to a Location with place name information.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees

        Returns:
            Location object with place names (city, county, state, country)

        Raises:
            GeocodingError: If geocoding fails
        """
        ...


class GeocodingError(Exception):
    """Raised when geocoding fails."""

    pass
