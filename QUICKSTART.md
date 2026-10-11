# Quick Start Guide

A short walkthrough using the bundled example and a small made-up track.

## 1. Install

```bash
pip install -e ".[dev]"
```

## 2. Run the example

`examples/basic_gpx_parse.py` parses a GPX file and prints the journey's start,
end, waypoint count, distance and elevation. With no argument it writes a tiny
three-point track to a temporary directory and parses that, so it runs without
any data of your own:

```bash
python examples/basic_gpx_parse.py
```

Pass your own file to parse it instead:

```bash
python examples/basic_gpx_parse.py path/to/track.gpx
```

## 3. A made-up track

Save this as `sample.gpx`:

```xml
<?xml version="1.0"?>
<gpx version="1.1" creator="example">
  <trk>
    <name>Sample Track</name>
    <trkseg>
      <trkpt lat="30.000" lon="-40.000"><ele>100</ele><time>2030-01-05T10:00:00Z</time></trkpt>
      <trkpt lat="30.100" lon="-40.100"><ele>150</ele><time>2030-01-05T11:00:00Z</time></trkpt>
      <trkpt lat="30.200" lon="-40.200"><ele>120</ele><time>2030-01-05T12:00:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
```

## 4. Command line

```bash
# Validate only
gps-journey validate sample.gpx

# Parse and summarise
gps-journey process sample.gpx

# With geocoding (network access to Nominatim), writing Hugo markdown
gps-journey process sample.gpx --geocode --output sample-trip.md
```

## 5. Python

```python
from pathlib import Path

from gps_journey.core.processor import JourneyProcessor
from gps_journey.hugo.generator import HugoGenerator

processor = JourneyProcessor(
    geocoding_enabled=True,
    geocoding_cache_path=Path(".geocode_cache.json"),
)
journey = processor.process(Path("sample.gpx"))

print(f"Waypoints: {len(journey.waypoints)}")
print(f"Start: {journey.start_location}")
print(f"End: {journey.end_location}")
print(f"Distance: {journey.statistics.total_distance_km:.1f} km")

generator = HugoGenerator(output_dir=Path("./output/journeys"))
output_path = generator.generate(journey, title="Sample Road Trip", slug="sample-trip")
print(f"Generated: {output_path}")
```

## 6. Using the generated page

The page is generated with `draft: false`; set `draft: true` in the front matter
if you want to hold it back. Review the markdown, add photos and narrative, copy
it into your Hugo site's content directory and preview it with `hugo server`.

`process --output` always writes `<name>.md` into the current directory (only the
file's stem is used). One environment variable points the commands at your site (see
`.env.example`): `HUGO_CONTENT_PATH` is where `export-metadata` looks for the
journey page. The `--static-dir` option is the only way to point
`HugoGenerator` at a static directory (it only reads `photo_mapping.json` when a
library caller supplies `gallery_path`; `process` does not); `HUGO_STATIC_PATH`
is reserved and no command reads it. A `HUGO__` value in `.env` wins over an
exported `HUGO_` variable.

## Geocoding cache

Geocoding results are cached in `.geocode_cache.json`, keyed by coordinates
rounded to four decimal places:

```json
{
  "30.0000,-40.0000": {
    "detailed": {
      "latitude": 30.0,
      "longitude": -40.0,
      "road": "Sample Road",
      "village": "Sample Village",
      "hamlet": null,
      "locality": null,
      "city_district": null,
      "suburb": null,
      "town": null,
      "city": null,
      "county": "Sample County",
      "state": "Sample Region",
      "country": "Sample Country",
      "postcode": null,
      "poi": null,
      "poi_name": null,
      "place_class": "highway",
      "match_type": "residential",
      "importance": 0.1,
      "place_rank": 26,
      "address_rank": 26,
      "addresstype": "road",
      "match_latitude": 30.0,
      "match_longitude": -40.0,
      "match_distance_km": 0.0,
      "full_address": "Sample Road, Sample Village, Sample County, Sample Region, Sample Country"
    },
    "detailed_timestamp": 1893837600.0
  }
}
```

Cached lookups return instantly, avoid Nominatim rate limits, expire after 90 days
(configurable) and are safe across processes through file locking.

## Troubleshooting

- **Geocoding times out or is rate limited:** from Python, pass a slower client:
  `JourneyProcessor(geocoding_enabled=True, geocoding_provider=NominatimRoadsClient(cache=cache, rate_limit=0.5))`
  (`NominatimRoadsClient` is in `gps_journey.geocoding.nominatim_roads`,
  `GeocodingCache` in `gps_journey.geocoding.cache`). The command line uses the
  default rate of one request per second.
- **Stale lock on the cache:** remove `.geocode_cache.lock`.
- **Want to re-geocode:** delete `.geocode_cache.json`.
