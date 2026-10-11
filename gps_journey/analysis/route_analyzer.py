"""Route analysis for detecting towns, roads, and route segments from GPS data."""

import logging
from collections.abc import Iterable
from math import asin, cos, radians, sin, sqrt

from gps_journey.core.models import Waypoint
from gps_journey.geocoding.nominatim_roads import MAX_SETTLEMENT_MATCH_KM

logger = logging.getLogger(__name__)

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon pairs in km."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


def calculate_distance_km(waypoints: Iterable[Waypoint]) -> float:
    """Total Haversine distance across an ordered waypoint trajectory, in km.

    Returns 0.0 for empty input or a single waypoint. Sums consecutive
    great-circle distances between waypoints in the order given. Use for
    journey-level or per-segment distance totals where Haversine accuracy
    (a few percent at typical driving scales) is sufficient.

    Public API, promoted from ``RouteAnalyzer._calculate_distance`` so
    downstream consumers can compute distance without instantiating a
    ``RouteAnalyzer``.
    """
    wp_list = list(waypoints)
    if len(wp_list) < 2:
        return 0.0
    total = 0.0
    for i in range(len(wp_list) - 1):
        total += _haversine_km(
            wp_list[i].latitude,
            wp_list[i].longitude,
            wp_list[i + 1].latitude,
            wp_list[i + 1].longitude,
        )
    return total


def calculate_elevation_gain_m(waypoints: Iterable[Waypoint]) -> float:
    """Total positive elevation gain across an ordered waypoint trajectory, in metres.

    Sums positive deltas only — descents are not counted. Waypoints with
    ``elevation is None`` on either side of a delta are skipped (matches
    the elevation handling in ``gps_journey.core.processor``). Returns
    ``0.0`` for empty input, single waypoint, or all-flat / all-descending
    trajectories.

    Public API, promoted from the inline computation in ``processor.py`` so
    downstream consumers (for example per-segment description enrichment)
    can compute elevation gain without processing a full Journey.
    """
    wp_list = list(waypoints)
    if len(wp_list) < 2:
        return 0.0
    total = 0.0
    for i in range(len(wp_list) - 1):
        e0 = wp_list[i].elevation
        e1 = wp_list[i + 1].elevation
        if e0 is None or e1 is None:
            continue
        delta = e1 - e0
        if delta > 0:
            total += delta
    return total


# Country-keyed admin-level selection for the regions-passed-through helper.
# Different countries draw the most useful "what region was this drive in?"
# answer from different fields of the Nominatim address record. Ireland's
# counties are coarse enough to be meaningful in a description and fine
# enough to distinguish drives; in the US, counties are far too granular
# (Kerr County, TX means nothing to a viewer), so the state component is
# the right granularity. Other countries default to ``county`` verbatim.
#
_REGION_ADMIN_LEVEL_BY_COUNTRY = {
    "ireland": "county",
    "usa": "state",
    "us": "state",
    "u.s.": "state",
    "u.s.a.": "state",
    "united states": "state",
    "united states of america": "state",
}


def _region_admin_level(country: str | None) -> str:
    """Pick the Nominatim address field for the regions-passed-through rule.

    Country lookup is case-insensitive. Returns ``"state"`` for US drives,
    ``"county"`` for Ireland and every other country (the default — most
    countries' counties / equivalent are at the right granularity).
    """
    if not country:
        return "county"
    return _REGION_ADMIN_LEVEL_BY_COUNTRY.get(country.strip().lower(), "county")


# Suffix patterns that indicate an OSM "village" is really an HOA, subdivision,
# trailer park, or apartment complex rather than a real town. These names leak
# into generated text as fake destinations — filter them at the source.
HOA_SUFFIX_PATTERNS = (
    " Subdivision",
    " Estates",
    " HOA",
    " Community",
    " Mobile Home",
    " Trailer Park",
    " Apartments",
)


def _is_hoa_name(name: str) -> bool:
    """True if the town name matches a known HOA/subdivision suffix pattern."""
    if not name:
        return False
    return any(name.endswith(suffix) for suffix in HOA_SUFFIX_PATTERNS)


class RouteAnalyzer:
    """
    Analyze GPS routes to extract towns, roads, and segments.

    Uses waypoint sampling to avoid geocoding every point.
    """

    def __init__(
        self,
        geocoder=None,
        sample_interval: int = 100,
    ):
        """
        Initialize route analyzer.

        Args:
            geocoder: Geocoder with reverse_geocode_detailed() method
            sample_interval: Sample every Nth waypoint (default: 100)
        """
        self.geocoder = geocoder
        self.sample_interval = sample_interval

    def get_towns_passed_through(
        self, waypoints: tuple[Waypoint, ...] | list[Waypoint]
    ) -> list[dict]:
        """
        Detect towns passed through by sampling and geocoding waypoints.

        HOA / subdivision / trailer park names are filtered out — these get
        tagged as "village" in OSM but are not real destinations.

        Args:
            waypoints: GPS waypoints from journey

        Returns:
            List of towns (chronological order) with entry/exit times and
            metadata for downstream ranking:
            [{
                'name': 'Alderford',
                'entered': datetime,
                'exited': datetime,
                'duration_minutes': int,     # always >= 5
                'place_class': str | None,   # OSM feature class, e.g. 'place'
                'importance': float,         # 0.0-1.0, 0.0 when unavailable
                'match_distance_km': float | None,  # closest query-to-match
                                             # distance across in-town samples
            }, ...]
        """
        if not self.geocoder:
            logger.warning("No geocoder provided, cannot detect towns")
            return []

        # Sample waypoints
        sampled = self._sample_waypoints(waypoints)

        logger.info(f"Analyzing route: {len(sampled)} sampled from {len(waypoints)} waypoints")

        # Track town transitions, accumulating per-town geocoder metadata
        # (max importance wins). A town's ``exited`` is stamped from the LAST
        # sample that geocoded INSIDE it — never from the next town's entry;
        # ``last_in_town_ts`` is that cursor. No-name samples (rural stretches,
        # HOA/subdivision names, rate-limited empty results) close the open
        # town at that cursor and reset ``current_town``, so a townless gap
        # can't inflate the town before it (which would let a briefly-clipped
        # crossroads evade the duration junk filter).
        current_town = None
        last_in_town_ts = None
        towns = []

        for waypoint in sampled:
            try:
                geo = self.geocoder.reverse_geocode_detailed(waypoint.latitude, waypoint.longitude)

                # Extract most specific location name
                town_name = (
                    geo.get("village") or geo.get("town") or geo.get("city") or geo.get("hamlet")
                )

                # Drop HOA / subdivision names at the source so they never
                # become "current_town" and can't leak into generated text. Treated
                # as a no-name sample below (closes/resets the open town).
                if _is_hoa_name(town_name):
                    logger.debug(f"Filtered HOA/subdivision name: {town_name}")
                    town_name = None

                # Match-distance signal: when the geocoder reports how far
                # the matched OSM object is from this waypoint, a far match
                # is a catchment feature — its address fields must not vote.
                # None (legacy cache / foreign geocoder) keeps today's path.
                match_km = geo.get("match_distance_km")
                if town_name and match_km is not None and match_km > MAX_SETTLEMENT_MATCH_KM:
                    logger.debug(f"Filtered far-match town vote: {town_name} ({match_km:.1f}km)")
                    town_name = None

                place_class = geo.get("place_class")
                importance = geo.get("importance")

                if not town_name:
                    # No-name sample: close the open town at its last in-town
                    # fix and reset, so this townless gap doesn't inflate it.
                    if current_town and towns and towns[-1]["exited"] is None:
                        towns[-1]["exited"] = last_in_town_ts
                    current_town = None
                elif town_name != current_town:
                    # Town boundary crossing. The previous town has already
                    # been closed at its last in-town fix by the no-name gap
                    # (or is closed here at that cursor if the towns abut).
                    if current_town and towns and towns[-1]["exited"] is None:
                        towns[-1]["exited"] = last_in_town_ts

                    # Entered new town — record entry coordinates so downstream
                    # endpoint derivation can verify whether the detected town is
                    # actually near the drive's start/end or just sampled in
                    # the middle of a long transit.
                    towns.append(
                        {
                            "name": town_name,
                            "entered": waypoint.timestamp,
                            "exited": None,
                            "place_class": place_class,
                            "importance": float(importance) if importance is not None else 0.0,
                            "match_distance_km": match_km,
                            "entry_latitude": waypoint.latitude,
                            "entry_longitude": waypoint.longitude,
                        }
                    )
                    current_town = town_name
                    last_in_town_ts = waypoint.timestamp
                else:
                    # Still inside the same town — advance the in-town cursor
                    # and upgrade metadata if this sample gives a stronger
                    # (higher importance) signal.
                    last_in_town_ts = waypoint.timestamp
                    existing = towns[-1]
                    sample_importance = float(importance) if importance is not None else 0.0
                    if sample_importance > existing["importance"]:
                        existing["importance"] = sample_importance
                    if existing["place_class"] is None and place_class is not None:
                        existing["place_class"] = place_class
                    # Keep the CLOSEST match distance — the strongest
                    # at-waypoint evidence this town saw across its samples.
                    if match_km is not None and (
                        existing["match_distance_km"] is None
                        or match_km < existing["match_distance_km"]
                    ):
                        existing["match_distance_km"] = match_km

            except Exception as e:
                logger.debug(f"Geocoding failed for waypoint: {e}")
                continue

        # Close a town still open at the end of the trace — the drive ended
        # inside it, so it runs to the final waypoint.
        if towns and towns[-1]["exited"] is None and waypoints:
            towns[-1]["exited"] = waypoints[-1].timestamp

        # Calculate durations and filter
        result = []
        for town in towns:
            if town["exited"]:
                duration_seconds = (town["exited"] - town["entered"]).total_seconds()
                duration_minutes = int(duration_seconds / 60)

                # Only include towns where we spent >=3 minutes. Downstream
                # consumers treat short-duration towns as junk-eligible
                # anyway, so a looser filter here admits real towns briefly
                # traversed on highway stretches without polluting endpoint
                # selection.
                if duration_minutes >= 3:
                    result.append(
                        {
                            **town,
                            "duration_minutes": duration_minutes,
                        }
                    )

        logger.info(f"Detected {len(result)} towns along route")
        return result

    def get_regions_passed_through(
        self,
        waypoints: tuple[Waypoint, ...] | list[Waypoint],
        country: str | None = None,
    ) -> list[dict]:
        """Detect administrative regions (counties / states) the route passes through.

        Mirrors ``get_towns_passed_through`` but at one admin level coarser
        — designed to power a "Through:" line in a long-form description.
        Admin level selection
        is country-keyed via ``_region_admin_level``: US drives use
        ``state``, Ireland and unspecified countries use ``county``.

        Sampling: sparse — every ``max(1, len(waypoints) // 20)``-th
        waypoint, so the API-call budget for any single segment is bounded at
        ~20 reverse-geocodes regardless of trajectory length. The existing
        on-disk Nominatim cache (and earlier calls covering the same
        coordinates) absorbs most of the cost. Sparse sampling can
        miss a region the route only briefly clips through; that's an
        acceptable trade for a bounded budget.

        Returns regions in chronological order, deduplicated against the
        immediately-preceding region. HOA / subdivision names are not a
        concern at this admin level, but the same ``_is_hoa_name`` filter
        is applied defensively. Ireland's county names are normalised to
        the ``"County <Name>"`` form if Nominatim omits the prefix.

        Args:
            waypoints: GPS waypoints from journey.
            country: Country name (e.g. ``"Ireland"``, ``"USA"``) used to
                pick the admin level. Case-insensitive; ``None`` defaults
                to county-level.

        Returns:
            List of regions (chronological order, adjacent-deduped):
            ``[{"name": "County Kerry", "country": "Ireland",
                "admin_level": "county"}, ...]``
        """
        if not self.geocoder:
            logger.warning("No geocoder provided, cannot detect regions")
            return []

        wp_list = list(waypoints)
        if not wp_list:
            return []

        admin_level = _region_admin_level(country)
        normalise = country and country.strip().lower() == "ireland"

        # Sparse sampling — at most ~20 reverse-geocodes per segment.
        step = max(1, len(wp_list) // 20)
        sampled = wp_list[::step]

        regions: list[dict] = []
        last_name: str | None = None
        for wp in sampled:
            try:
                geo = self.geocoder.reverse_geocode_detailed(wp.latitude, wp.longitude)
            except Exception as e:
                logger.debug(f"Geocoding failed for waypoint: {e}")
                continue

            name = geo.get(admin_level)
            if not name:
                continue
            if _is_hoa_name(name):
                continue
            if normalise and not name.startswith("County "):
                name = f"County {name}"

            if name == last_name:
                continue
            regions.append(
                {
                    "name": name,
                    "country": country,
                    "admin_level": admin_level,
                }
            )
            last_name = name

        logger.info(f"Detected {len(regions)} regions along route ({admin_level})")
        return regions

    def get_road_segments(self, waypoints: tuple[Waypoint, ...] | list[Waypoint]) -> list[dict]:
        """
        Detect road segments traveled.

        Args:
            waypoints: GPS waypoints from journey

        Returns:
            List of road segments:
            [{
                'road': 'N99',
                'distance_km': 25.3,
                'start_time': datetime,
                'end_time': datetime
            }, ...]
        """
        if not self.geocoder:
            logger.warning("No geocoder provided, cannot detect roads")
            return []

        # Sample waypoints
        sampled = self._sample_waypoints(waypoints)
        raw_waypoints = list(waypoints)
        n_sampled = len(sampled)

        # Track road transitions. A segment closes at the LAST sample that
        # returned that road (``last_road_idx``) — never extended across
        # unnamed / rate-limited (``road=None``) samples. This keeps a
        # townless or rate-limited gap from being credited to the road before
        # it, which would inflate the downstream >50% dominant-road guard.
        current_road = None
        segments = []
        segment_start_idx = 0
        last_road_idx = 0

        def _append_segment(road: str, start_idx: int, end_idx: int) -> None:
            # Map sampled indices back to raw waypoints. The segment spans the
            # raw waypoints from its first sample up to (and including) the
            # interval of its last real sample. When that last sample is the
            # final sample, the drive ended on this road, so run to the end.
            raw_start = start_idx * self.sample_interval
            if end_idx >= n_sampled - 1:
                segment_wps = raw_waypoints[raw_start:]
            else:
                segment_wps = raw_waypoints[raw_start : (end_idx + 1) * self.sample_interval]
            if segment_wps:
                segments.append(
                    {
                        "road": road,
                        "distance_km": self._calculate_distance(segment_wps),
                        "start_time": segment_wps[0].timestamp,
                        "end_time": segment_wps[-1].timestamp,
                    }
                )

        for idx, waypoint in enumerate(sampled):
            try:
                geo = self.geocoder.reverse_geocode_detailed(waypoint.latitude, waypoint.longitude)
                road_name = geo.get("road")
            except Exception as e:
                logger.debug(f"Geocoding failed: {e}")
                continue

            if not road_name:
                # Unnamed / rate-limited sample: close the open segment at its
                # last real-road sample. It must not extend across the gap.
                if current_road is not None:
                    _append_segment(current_road, segment_start_idx, last_road_idx)
                    current_road = None
            elif road_name != current_road:
                # New road: close the previous segment at its last real sample.
                if current_road is not None:
                    _append_segment(current_road, segment_start_idx, last_road_idx)
                current_road = road_name
                segment_start_idx = idx
                last_road_idx = idx
            else:
                # Same road continues — advance the cursor to this sample.
                last_road_idx = idx

        # Close the final open segment at its last real sample.
        if current_road is not None:
            _append_segment(current_road, segment_start_idx, last_road_idx)

        logger.info(f"Detected {len(segments)} road segments")
        return segments

    def _sample_waypoints(self, waypoints: tuple[Waypoint, ...] | list[Waypoint]) -> list[Waypoint]:
        """Sample waypoints at regular intervals."""
        waypoint_list = list(waypoints)
        return waypoint_list[:: self.sample_interval]

    def _calculate_distance(self, waypoints: list[Waypoint]) -> float:
        """Calculate total distance using Haversine formula.

        Delegates to the module-level ``calculate_distance_km`` public
        helper (single source of truth).
        """
        return calculate_distance_km(waypoints)

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km.

        Delegates to the module-level ``_haversine_km`` helper.
        """
        return _haversine_km(lat1, lon1, lat2, lon2)
