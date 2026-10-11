"""GPS Journey Service - Transform GPS tracks into travel narratives."""

import importlib.metadata as _metadata

try:
    __version__ = _metadata.version("gps-journey")
except _metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"
