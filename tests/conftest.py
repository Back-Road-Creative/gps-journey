"""Pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path

# Ensure the package root is on sys.path so gps_journey subpackages resolve
# correctly regardless of editable install method.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Keep Hypothesis's example database and constants cache inside the ignored
# ``.cache/`` directory instead of creating ``.hypothesis/`` in the tree root.
os.environ.setdefault(
    "HYPOTHESIS_STORAGE_DIRECTORY", str(Path(_project_root) / ".cache" / "hypothesis")
)

import pytest  # noqa: E402


@pytest.fixture
def sample_waypoints():
    """Sample waypoints for testing."""
    from datetime import datetime

    from gps_journey.core.models import Waypoint

    return [
        Waypoint(
            latitude=10.0,
            longitude=20.0,
            timestamp=datetime(2030, 1, 1, 10, 0, 0),
            elevation=100.0,
        ),
        Waypoint(
            latitude=10.1,
            longitude=20.1,
            timestamp=datetime(2030, 1, 1, 11, 0, 0),
            elevation=150.0,
        ),
        Waypoint(
            latitude=10.2,
            longitude=20.2,
            timestamp=datetime(2030, 1, 1, 12, 0, 0),
            elevation=120.0,
        ),
    ]
