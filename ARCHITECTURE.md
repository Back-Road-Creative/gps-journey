# GPS Journey - Architecture

**Status:** Development

This document describes what is in the tree today. Ideas that are not built are
listed once, under [Not implemented](#not-implemented).

## Overview

gps-journey turns a GPX track into a journey model, optionally enriches it with
reverse-geocoded place names and matched photos, and writes Hugo markdown and
interactive maps.

```
GPX file -> GPXParser -> Journey -> (geocoding, photo matching) -> Hugo markdown / Folium map
```

External services: OpenStreetMap Nominatim (reverse geocoding, no key) and the
Google Photos API (OAuth 2.0, read-only scope). `AINarrativeGenerator` can also run an external LLM command-line tool as a subprocess, sending journey data to that service; without the tool on `PATH` it falls back to a factual narrative. All three are optional.

## Modules

```
gps_journey/
├── core/            models.py, gpx_parser.py, gpx_exporter.py, timeline.py, processor.py
├── geocoding/       base.py (provider protocol), nominatim.py, nominatim_roads.py, cache.py
├── photos/          client.py, oauth.py, exif.py, matcher.py, grouper.py,
│                    filesystem_loader.py, optimizer.py, models.py
├── analysis/        route_analyzer.py (towns, roads, regions, distance, elevation)
├── narrative/       simple_generator.py, ai_generator.py, photo_day_matcher.py
├── hugo/            generator.py, journal_writer.py, markdown_updater.py,
│                    narrative_generator.py
├── visualization/   map_generator.py, a11y.py, simplify.py
├── export/          journey_exporter.py
├── config.py        Pydantic settings
└── cli.py           Typer command-line interface
```

### Core

- `GPXParser` parses GPX 1.0/1.1 with gpxpy into an immutable `Journey`
  (dates, waypoints, statistics: distance, elevation gain/loss, speeds).
- `JourneyProcessor` parses a track and, when geocoding is enabled, resolves the
  start and end locations. It accepts a custom `geocoding_provider`, otherwise it
  uses `NominatimRoadsClient`, optionally backed by a `GeocodingCache` file.
  `generate_daily_breakdowns` groups waypoints and photos by calendar day.
- `Timeline` merges track points, photos and waypoints chronologically.

### Geocoding

- `GeocodingProvider` is a `Protocol` with `reverse_geocode(lat, lon) -> Location`.
- `NominatimClient` and `NominatimRoadsClient` call Nominatim with a configurable
  requests-per-second limit (default 1.0). `Location` keeps `town`, `village`
  and `hamlet` separate so rural places resolve to a real settlement.
- `GeocodingCache` is a JSON file keyed by coordinates rounded to four decimal
  places (about 11 m), guarded by a file lock, with a time-to-live (default 90
  days). Expired entries are ignored on read but stay in the file until overwritten or the cache is cleared; there is no eviction.

### Photos

- `GooglePhotosClient` and `GooglePhotosAuth` list albums and fetch photo
  metadata through the Google Photos API (OAuth 2.0, read-only scope).
- `EXIFExtractor` reads GPS position and capture time; `FilesystemPhotoLoader`
  loads photos from a local directory; `PhotoOptimizer` resizes and re-encodes
  images for the web.
- `PhotoMatcher` matches photos to the track by timestamp within a tolerance
  window (default five minutes). The distance is `None` unless the photo has its
  own GPS fix (never a `0.0` placeholder). Each match records the time offset,
  the surrounding track gap, the tolerance and a measured or inferred status. An
  optional `PublicationPolicy` refuses sparse-track matches, and naive camera
  timestamps need an explicit `camera_clock` (offset or IANA zone); otherwise
  they are reported as `needs_clock_decision`, never assumed to be UTC.
- `PhotoLocationGrouper` groups photos chronologically and geographically.

### Analysis and narrative

- `RouteAnalyzer` finds the towns, roads and regions a route passes through and
  provides distance and elevation helpers.
- `SimpleNarrativeGenerator`, `FactualNarrativeGenerator` and
  `AINarrativeGenerator` produce narrative text; `PhotoDayMatcher` assigns photos
  to days.

### Hugo

- `HugoGenerator` writes a markdown file with YAML front matter for a journey. It
  writes into `output_dir` (default: the current directory) and looks up
  `photo_mapping.json` under the optional `static_dir` first, then relative to the
  current directory.
- `HugoMarkdownUpdater` updates existing journey pages. `JournalWriter` builds a factual day-by-day journal text from a `Journey` and returns it as a string; it does not touch journey pages. Given a geocoder, it looks up each stop through Nominatim (and through that client's cache file, if one is configured); without a geocoder it keeps no stops.

### Visualization

- `MapGenerator` writes Folium HTML maps: route polyline, waypoint and photo
  markers, several tile layers. `simplify.py` reduces polylines with the
  Douglas-Peucker algorithm before rendering.
- Every map is written through `_save_accessible`, never `map_obj.save()`
  directly. Folium's stock template emits no `lang`, no `<title>` and
  `user-scalable=no`; `visualization/a11y.py` repairs all three on the rendered
  HTML, and `tests/unit/test_map_a11y.py` fails if a new save call site bypasses
  it.

## Design principles

1. **Immutable data models.** `Journey`, `Location` and `Photo` are frozen
   dataclasses; changes return a new object.
2. **Provider abstraction.** Geocoding is a protocol, so a test or another
   service can be swapped in.
3. **Aggressive caching.** Geocoding is slow and rate limited, so results are
   cached on disk.
4. **Error recovery.** Missing EXIF, failed geocoding or an unavailable photo
   source degrade the result instead of aborting it.

## Configuration

`gps_journey/config.py` defines Pydantic settings read from environment
variables and a `.env` file; `.env.example` lists the supported variables.
`Config.from_yaml` loads the same structure for library use. Fields, flat per
section: `geocoding` (`provider`, `rate_limit`, `cache_enabled`, `cache_path`,
`cache_ttl_days`, `nominatim_user_agent`, `google_api_key`), `google_photos`
(`client_id`, `client_secret`, `project_id`, `credentials_path`, `token_path`,
`scopes`, `download_photos`), `hugo` (`content_path`, `image_path`, `map_path`,
`static_path`, `archetype`), `maps` (`provider`, `tile_layer`, `width`,
`height`), `processing` (`min_stop_duration_seconds`,
`photo_match_tolerance_seconds`, `waypoint_distance_threshold_meters`) and
`log_level`.

The CLI reads `hugo.content_path` (for `export-metadata`). `HugoGenerator`
receives only the `--static-dir` option; `hugo.static_path`, `image_path` and
`map_path` are reserved and no command reads them. `process` never asks the
generator to look up `photo_mapping.json` (no `gallery_path` is passed);
library users can read the settings. Hugo locations have no defaults.

## Command line

| Command | Purpose |
|---------|---------|
| `process <gpx>` | Parse a track and print a summary. `--geocode` resolves start and end; `--output NAME.md` writes Hugo markdown named after the file's stem into the current directory; `--static-dir` is forwarded to `HugoGenerator` but currently has no effect in `process`. `--photos` and `--map` currently print a not-yet-available message. |
| `validate <gpx>` | Check that a track parses. |
| `export-metadata <id>` | Read a journey page from the Hugo content directory (`--hugo-dir`, `HUGO_CONTENT_PATH`, else `./output/journeys`) and write metadata JSON. |
| `version` | Print the version. |

## Testing

Tests live under `tests/` (`tests/unit/` plus a few top-level modules) and build
their GPX documents, photos and journeys in code or under pytest's `tmp_path`;
`tests/fixtures/` holds no data files. HTTP, OAuth and the file system are
mocked. Continuous integration is defined in `.github/workflows/ci.yml`.

## Not implemented

- Command-line support for photos and maps (`--photos`, `--map` are placeholders),
  and commands for OAuth setup, album listing and cache management.
- Elevation profile and statistics charts, landmark detection, weather data.
- Google and Mapbox geocoding clients (the `provider` setting accepts the names;
  only Nominatim clients exist).
- Template-based page rendering, asynchronous geocoding and a service API.
