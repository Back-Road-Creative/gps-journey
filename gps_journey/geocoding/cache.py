"""File-based geocoding cache with TTL and file locking."""

import json
import logging
import time
from pathlib import Path

from filelock import FileLock

from gps_journey.core.models import Location

logger = logging.getLogger(__name__)


class GeocodingCache:
    """
    Thread-safe file-based cache for geocoding results.

    Uses file locking to prevent concurrent write conflicts.
    Implements TTL (time-to-live) for cache expiration.
    """

    def __init__(self, cache_path: Path, ttl_days: int = 90):
        """
        Initialize the geocoding cache.

        Args:
            cache_path: Path to cache file (JSON)
            ttl_days: Time-to-live in days (default: 90)
        """
        self.cache_path = Path(cache_path)
        self.lock_path = self.cache_path.with_suffix(".lock")
        self.ttl_seconds = ttl_days * 86400  # Convert days to seconds
        self._ensure_cache_exists()

    def _ensure_cache_exists(self) -> None:
        """Create cache file if it doesn't exist."""
        if not self.cache_path.exists():
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump({}, f)

    def _make_key(self, latitude: float, longitude: float) -> str:
        """
        Create cache key from coordinates.

        Uses 4 decimal places (~11 meter precision) to balance
        cache hit rate with location accuracy.
        """
        return f"{latitude:.4f},{longitude:.4f}"

    def _location_from_detailed(
        self, latitude: float, longitude: float, detailed: dict
    ) -> Location:
        """Reconstruct a Location from a `detailed` cache dict.

        The roads geocoder writes reverse-geocode results into the `detailed`
        namespace (via `set_detailed`), so `get()` must be able to serve a
        Location from that dict too. Mirrors the field mapping the roads client
        uses when it builds a Location from the same dict, so a budget-exhausted
        chapter run served from the detailed cache gets the same settlement /
        road fields it would from a live reverse_geocode.
        """
        return Location(
            latitude=latitude,
            longitude=longitude,
            name=(
                detailed.get("village")
                or detailed.get("town")
                or detailed.get("city")
                or detailed.get("locality")
            ),
            locality=detailed.get("locality"),
            suburb=detailed.get("suburb"),
            city=detailed.get("city"),
            town=detailed.get("town"),
            village=detailed.get("village"),
            hamlet=detailed.get("hamlet"),
            county=detailed.get("county"),
            state=detailed.get("state"),
            country=detailed.get("country"),
            address=detailed.get("full_address"),
        )

    def get(self, latitude: float, longitude: float) -> Location | None:
        """
        Get cached location if available and not expired.

        Serves a Location from EITHER cache namespace: a fresh `location`
        sub-key (written by `set()`) is preferred; otherwise it reconstructs a
        Location from a fresh `detailed` sub-key (written by `set_detailed()` —
        the namespace the roads geocoder actually populates). Each namespace is
        expired against its own timestamp (`timestamp` for `location`,
        `detailed_timestamp` for `detailed`), so a warm `detailed`-only cache is
        served instead of being mis-treated as expired-and-empty.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees

        Returns:
            Cached Location object, or None if not cached or expired
        """
        key = self._make_key(latitude, longitude)

        with FileLock(self.lock_path):
            try:
                with open(self.cache_path) as f:
                    cache_data = json.load(f)

                entry = cache_data.get(key)
                if not entry:
                    return None

                current_time = time.time()

                # Prefer a fresh `location` sub-key (written by set()).
                location_data = entry.get("location")
                if location_data is not None:
                    cached_time = entry.get("timestamp", 0)
                    if current_time - cached_time <= self.ttl_seconds:
                        return Location(
                            latitude=latitude,
                            longitude=longitude,
                            name=location_data.get("name"),
                            city=location_data.get("city"),
                            town=location_data.get("town"),
                            village=location_data.get("village"),
                            hamlet=location_data.get("hamlet"),
                            county=location_data.get("county"),
                            state=location_data.get("state"),
                            country=location_data.get("country"),
                            address=location_data.get("address"),
                        )
                    logger.debug(f"Cache expired for {key}")

                # Fall back to the `detailed` sub-key (the namespace the roads
                # geocoder writes), expired against its own detailed_timestamp.
                detailed = entry.get("detailed")
                if detailed is not None:
                    detailed_time = entry.get("detailed_timestamp", entry.get("timestamp", 0))
                    if current_time - detailed_time <= self.ttl_seconds:
                        return self._location_from_detailed(latitude, longitude, detailed)
                    logger.debug(f"Detailed cache expired for {key}")

                return None

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Cache read error: {e}")
                return None

    def set(self, latitude: float, longitude: float, location: Location) -> None:
        """
        Store location in cache with current timestamp.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            location: Location object to cache
        """
        key = self._make_key(latitude, longitude)

        with FileLock(self.lock_path):
            try:
                with open(self.cache_path) as f:
                    cache_data = json.load(f)

                cache_data[key] = {
                    "timestamp": time.time(),
                    "location": {
                        "name": location.name,
                        "city": location.city,
                        "town": location.town,
                        "village": location.village,
                        "hamlet": location.hamlet,
                        "county": location.county,
                        "state": location.state,
                        "country": location.country,
                        "address": location.address,
                    },
                }

                with open(self.cache_path, "w") as f:
                    json.dump(cache_data, f, indent=2)

                logger.debug(f"Cached location for {key}")

            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Cache write error: {e}")

    def get_detailed(self, latitude: float, longitude: float) -> dict | None:
        """Get cached reverse-geocode-detailed dict if available and not expired.

        Separate from `get()` because reverse_geocode_detailed returns a full
        address dict (with fields like hamlet, match_type, boundingbox, etc.)
        that the Location object in `get()` can't represent. Detailed dicts
        are stored under a `"detailed"` key to avoid collision with the
        Location-based entries written by `set()`.
        """
        key = self._make_key(latitude, longitude)
        with FileLock(self.lock_path):
            try:
                with open(self.cache_path) as f:
                    cache_data = json.load(f)
                entry = cache_data.get(key)
                if not entry:
                    return None
                detailed = entry.get("detailed")
                if detailed is None:
                    return None
                cached_time = entry.get("detailed_timestamp", entry.get("timestamp", 0))
                if time.time() - cached_time > self.ttl_seconds:
                    return None
                return detailed
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Detailed cache read error: {e}")
                return None

    def set_detailed(self, latitude: float, longitude: float, detailed: dict) -> None:
        """Store a reverse-geocode-detailed dict in the cache with a
        separate timestamp from the Location entry (they can coexist)."""
        key = self._make_key(latitude, longitude)
        with FileLock(self.lock_path):
            try:
                with open(self.cache_path) as f:
                    cache_data = json.load(f)
                entry = cache_data.get(key, {})
                entry["detailed"] = detailed
                entry["detailed_timestamp"] = time.time()
                cache_data[key] = entry
                with open(self.cache_path, "w") as f:
                    json.dump(cache_data, f, indent=2)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Detailed cache write error: {e}")

    def clear(self) -> None:
        """Clear all cached entries."""
        with FileLock(self.lock_path):
            with open(self.cache_path, "w") as f:
                json.dump({}, f)
            logger.info("Cache cleared")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats (total entries, size, etc.)
        """
        with FileLock(self.lock_path):
            try:
                with open(self.cache_path) as f:
                    cache_data = json.load(f)

                total_entries = len(cache_data)
                expired_count = 0
                current_time = time.time()

                for entry in cache_data.values():
                    cached_time = entry.get("timestamp", 0)
                    if current_time - cached_time > self.ttl_seconds:
                        expired_count += 1

                file_size_kb = self.cache_path.stat().st_size / 1024

                return {
                    "total_entries": total_entries,
                    "expired_entries": expired_count,
                    "active_entries": total_entries - expired_count,
                    "file_size_kb": round(file_size_kb, 2),
                }

            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Stats read error: {e}")
                return {
                    "total_entries": 0,
                    "expired_entries": 0,
                    "active_entries": 0,
                    "file_size_kb": 0.0,
                }
