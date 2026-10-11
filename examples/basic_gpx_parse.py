#!/usr/bin/env python3
"""Basic example of parsing a GPX file and displaying journey information.

Usage:
    python examples/basic_gpx_parse.py [track.gpx]

With no argument the example writes a small three-point track to a temporary
directory and parses that, so it runs without any data of your own.
"""

import sys
import tempfile
from pathlib import Path

from gps_journey.core.gpx_parser import GPXParser

SAMPLE_GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="gps-journey example">
  <trk>
    <name>Sample Track</name>
    <trkseg>
      <trkpt lat="30.000" lon="-40.000"><ele>100</ele><time>2030-01-05T10:00:00Z</time></trkpt>
      <trkpt lat="30.100" lon="-40.100"><ele>150</ele><time>2030-01-05T11:00:00Z</time></trkpt>
      <trkpt lat="30.200" lon="-40.200"><ele>120</ele><time>2030-01-05T12:00:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def describe(gpx_file: Path) -> None:
    """Parse ``gpx_file`` and print the journey attributes."""
    journey = GPXParser().parse(gpx_file)
    stats = journey.statistics

    print("GPS Journey - Basic GPX Parsing Example")
    print("=" * 60)
    print(f"File:       {gpx_file.name}")
    print(f"Start:      {journey.start_date}")
    print(f"End:        {journey.end_date}")
    print(f"Waypoints:  {len(journey.waypoints)}")
    if stats is not None:
        print(f"Distance:   {stats.total_distance_km:.1f} km ({stats.total_distance_miles:.1f} mi)")
        print(
            f"Elevation:  +{stats.total_elevation_gain_m:.0f} m / "
            f"-{stats.total_elevation_loss_m:.0f} m"
        )


def main() -> None:
    """Parse the GPX file named on the command line, or a built-in sample."""
    if len(sys.argv) > 1:
        describe(Path(sys.argv[1]))
        return

    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "sample.gpx"
        sample.write_text(SAMPLE_GPX, encoding="utf-8")
        describe(sample)


if __name__ == "__main__":
    main()
