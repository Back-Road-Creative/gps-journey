"""
GPS Journey Visualization Module

Provides map generation and visualization tools for GPS journey data.
"""

from gps_journey.visualization.map_generator import MapGenerator
from gps_journey.visualization.simplify import simplify_polyline

__all__ = ["MapGenerator", "simplify_polyline"]
