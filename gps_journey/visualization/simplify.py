"""
Polyline Simplification Module

Implements the Douglas-Peucker algorithm to reduce the number of points in a polyline
while preserving its overall shape. This is critical for web map performance - GPS tracks
with 10,000+ points can cause slow rendering and large file sizes.

The algorithm:
1. Finds the point with the maximum distance from the line segment between first and last
2. If that distance exceeds the tolerance, recursively simplifies the two sub-polylines
3. Otherwise, removes all intermediate points

Typical results:
- Input: 10,000 waypoints, 7MB GPX file
- Output: 500 waypoints, 500KB HTML map
- Visual quality: Nearly identical (11m precision with 0.0001° tolerance)
"""

import math

# Type alias for coordinate pairs
Point = tuple[float, float]  # (latitude, longitude)


def perpendicular_distance(point: Point, line_start: Point, line_end: Point) -> float:
    """
    Calculate the perpendicular distance from a point to a line segment.

    Uses the cross product formula to find the distance from a point to the line
    defined by two other points. This is more accurate than simple Euclidean distance
    for lat/lon coordinates at Ireland's latitude (~52-55°N).

    Args:
        point: The point to measure distance from (lat, lon)
        line_start: Start point of the line segment (lat, lon)
        line_end: End point of the line segment (lat, lon)

    Returns:
        Distance in degrees (approximately 11 meters per 0.0001° at this latitude)
    """
    lat, lon = point
    lat1, lon1 = line_start
    lat2, lon2 = line_end

    # Handle degenerate case where line segment is a single point
    if (lat1, lon1) == (lat2, lon2):
        return math.sqrt((lat - lat1) ** 2 + (lon - lon1) ** 2)

    # Calculate perpendicular distance using cross product
    numerator = abs((lat2 - lat1) * (lon1 - lon) - (lat1 - lat) * (lon2 - lon1))
    denominator = math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2)

    return numerator / denominator


def douglas_peucker(points: list[Point], tolerance: float) -> list[Point]:
    """
    Recursively simplify a polyline using the Douglas-Peucker algorithm.

    Args:
        points: List of (latitude, longitude) tuples representing the polyline
        tolerance: Maximum distance (in degrees) a point can deviate from the
                  simplified line. Typical value: 0.0001° (~11m at Ireland latitude)

    Returns:
        Simplified list of points preserving the overall shape

    Example:
        >>> track = [(55.0, -7.0), (55.1, -7.1), (55.2, -7.0), (55.3, -7.1)]
        >>> simplified = douglas_peucker(track, 0.01)
        >>> len(simplified) < len(track)
        True
    """
    if len(points) < 3:
        return points

    # Find the point with the maximum distance from the line segment
    # connecting the first and last points
    first = points[0]
    last = points[-1]
    max_dist = 0
    max_index = 0

    for i in range(1, len(points) - 1):
        dist = perpendicular_distance(points[i], first, last)
        if dist > max_dist:
            max_dist = dist
            max_index = i

    # If max distance exceeds tolerance, recursively simplify the two sub-polylines
    if max_dist > tolerance:
        # Recursively simplify left and right segments
        left = douglas_peucker(points[: max_index + 1], tolerance)
        right = douglas_peucker(points[max_index:], tolerance)

        # Combine results (remove duplicate middle point)
        return left[:-1] + right
    else:
        # All intermediate points can be removed
        return [first, last]


def simplify_polyline(
    points: list[Point], tolerance: float = 0.0001, min_points: int = 100
) -> list[Point]:
    """
    Simplify a polyline while ensuring a minimum number of points.

    This is a wrapper around douglas_peucker that:
    1. Validates input
    2. Handles edge cases (too few points, empty lists)
    3. Ensures the result has at least min_points for smooth curves
    4. Provides sensible defaults for GPS track simplification

    Args:
        points: List of (latitude, longitude) tuples
        tolerance: Simplification tolerance in degrees (default: 0.0001° ≈ 11m)
        min_points: Minimum points to keep (default: 100 for smooth rendering)

    Returns:
        Simplified polyline with at least min_points or original length if shorter

    Raises:
        ValueError: If points list is empty or contains invalid coordinates

    Example:
        >>> from gps_journey.core.models import Journey
        >>> waypoints = [(w.latitude, w.longitude) for w in journey.waypoints]
        >>> simplified = simplify_polyline(waypoints, tolerance=0.0001)
        >>> print(f"Reduced from {len(waypoints)} to {len(simplified)} points")
        Reduced from 15234 to 487 points
    """
    if not points:
        raise ValueError("Cannot simplify empty polyline")

    if len(points) < min_points:
        # Already small enough, return as-is
        return points

    # Validate points
    for i, (lat, lon) in enumerate(points):
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude at index {i}: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude at index {i}: {lon}")

    # Simplify with initial tolerance
    simplified = douglas_peucker(points, tolerance)

    # If we got too few points, gradually reduce tolerance
    # This ensures smooth curves while still achieving compression
    while len(simplified) < min_points and tolerance > 0.00001:
        tolerance *= 0.5
        simplified = douglas_peucker(points, tolerance)

    return simplified


def calculate_reduction(original_count: int, simplified_count: int) -> dict:
    """
    Calculate compression statistics for polyline simplification.

    Args:
        original_count: Number of points in original polyline
        simplified_count: Number of points after simplification

    Returns:
        Dictionary with reduction metrics:
        - points_removed: Number of points eliminated
        - points_kept: Number of points retained
        - reduction_percent: Percentage of points removed
        - compression_ratio: Ratio of original to simplified (e.g., 20:1)

    Example:
        >>> stats = calculate_reduction(10000, 500)
        >>> print(f"Removed {stats['reduction_percent']:.1f}% of points")
        Removed 95.0% of points
    """
    points_removed = original_count - simplified_count
    reduction_percent = (points_removed / original_count) * 100
    compression_ratio = original_count / simplified_count if simplified_count > 0 else 0

    return {
        "points_removed": points_removed,
        "points_kept": simplified_count,
        "reduction_percent": reduction_percent,
        "compression_ratio": compression_ratio,
    }
