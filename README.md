# gps-journey

**Status:** Development

Turns GPS tracking data into travel narratives: GPX parsing, reverse geocoding, photo matching against the track, interactive maps and Hugo content generation.

## Features

- GPX import and parsing (waypoints, tracks, routes), trip timeline and statistics (distance, elevation, speed)
- Reverse geocoding through OpenStreetMap Nominatim with an on-disk cache
- Photo integration: EXIF extraction, matching photos to the GPS timeline (with explicit uncertainty and camera-clock handling), chronological and geographic grouping, image optimisation
- Hugo markdown export, including photo galleries
- Interactive Folium maps
- Journey metadata export (`export-metadata`) for downstream tooling

Per-day breakdowns of waypoints and photos (`JourneyProcessor.generate_daily_breakdowns`).

Not implemented yet: elevation profiles, separate per-day pages, landmark detection, weather data.

---

## Architecture

```
gps_journey/
├── core/            # Journey models, GPX parser/exporter, timeline, processor
├── geocoding/       # Geocoding interface, Nominatim clients, cache
├── photos/          # Google Photos client/OAuth, EXIF, optimizer, matcher, grouping
├── analysis/        # Route analysis (towns, roads, regions, distance, elevation)
├── narrative/       # Narrative generators
├── hugo/            # Hugo markdown generation and updating
├── visualization/   # Folium map generation
├── export/          # Journey metadata export
├── config.py        # Settings (environment / .env)
└── cli.py           # Command-line interface
examples/            # Runnable examples
scripts/             # Helper scripts
tests/               # Test suite
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design in detail.

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Core Language | Python 3.10+ | Main implementation |
| GPX Parsing | gpxpy | GPX file parsing |
| Geocoding | geopy | OpenStreetMap Nominatim |
| Photos API | google-api-python-client | Google Photos integration |
| OAuth | google-auth-oauthlib | OAuth 2.0 authentication |
| EXIF | Pillow | Photo metadata extraction |
| Maps | folium | Interactive map generation |
| HTTP | httpx | HTTP client |
| CLI | typer | Command-line interface |
| Testing | pytest | Unit and integration tests |
| Linting | ruff | Code quality |

---

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for a walkthrough.

### Installation

```bash
git clone <repository-url> gps-journey
cd gps-journey
pip install -e .
```

### Basic Usage

```python
from gps_journey.core.gpx_parser import GPXParser

journey = GPXParser().parse("path/to/track.gpx")
print(journey.start_date, journey.end_date, len(journey.waypoints))
print(journey.statistics.total_distance_km)
```

To geocode and write Hugo markdown, use `JourneyProcessor` and `HugoGenerator`
(see [QUICKSTART.md](QUICKSTART.md)).

### CLI Usage

```bash
# Validate a GPX file
gps-journey validate track.gpx

# Parse a GPX file and print a summary
gps-journey process track.gpx

# With geocoding, writing Hugo markdown
gps-journey process track.gpx --geocode --output my-trip.md

# Export journey metadata from an existing Hugo journey page
gps-journey export-metadata my-trip --hugo-dir ./content/journeys -o journey.json

gps-journey version
```

---

## Helper scripts

Run from the repository root; each is a plain command-line script, separate from the `gps-journey` command.

| Script | Purpose |
|--------|---------|
| `scripts/generate_narrative.py --gpx FILE --title TEXT --output FILE.md [--cache PATH]` | Geocodes a track (start, end, roads, towns, stops at named places) and writes a day-by-day markdown narrative. `--cache` defaults to `.cache/geocode_cache.json`. Queries Nominatim at one request per second, so a long track takes a while. |
| `scripts/process_local_photos.py` | Optimises a local photo folder, matches the photos to a track and prints gallery metadata. `--hugo-static-dir` defaults to `./output/static`. |
| `scripts/extract_journey_data.py` | Extracts journey data from a track (and optionally a photo folder) into a JSON file. |

`generate_narrative.py` can optionally record each finished narrative in an
external "IntelDB" SQLite database. This is off unless both `INTEL_DB_PATH` (the
database file) and `INTEL_SCRIPTS_DIR` (a directory holding an `intel_db.py` that
defines `IntelDB`) are set; the module is loaded from that file and nothing is
added to `sys.path`. `INTEL_PLATFORM` sets the platform label stored with each
run (default `gps-journey`; earlier versions of the script recorded `gomoveshift-gps`, so set
`INTEL_PLATFORM=gomoveshift-gps` to keep one history with those runs). A failure to load or
write is reported as a warning and never stops the script.

---

## Configuration

Settings are read from environment variables and from a `.env` file in the
current directory; see `.env.example` for the supported variables. `Config.from_yaml`
loads the same structure from YAML for library use (the CLI does not read a YAML
file).

```yaml
geocoding:
  provider: nominatim
  cache_enabled: true
  cache_path: .geocode_cache.json
  rate_limit: 1.0  # requests per second

hugo:
  # No defaults: point these at your own Hugo site.
  content_path: ./content/journeys
  static_path: ./static
  archetype: journey
```

Hugo locations have no built-in defaults. `HUGO_CONTENT_PATH` (or
`HUGO__CONTENT_PATH` in `.env`) is where `export-metadata` looks for the journey
page; the CLI option `--hugo-dir` overrides it, and it falls back to
`./output/journeys` when unset or blank. The static directory reaches
`HugoGenerator` only through the `--static-dir` option; `HugoGenerator` reads
`photo_mapping.json` from it when a library caller passes `gallery_path` to
`generate()`, and `process` does not use it yet. `static_path`
(`HUGO_STATIC_PATH` / `HUGO__STATIC_PATH`), `image_path` and `map_path` are
reserved settings that no command reads. Precedence: a `HUGO__` value in `.env`
wins over an exported `HUGO_` variable. To override a `.env`, export
`HUGO__CONTENT_PATH` or use the CLI options. `process --output` writes
`<name>.md` into the current directory; copy it into your site afterwards.

### Private inputs

Files that belong to you rather than to the package (a `config.yaml` for
`Config.from_yaml`, location overrides) live in one directory, found with
`gps_journey.config.inputs_dir()`. Set `GPS_INPUTS_DIR` to point at it; without
it the directory is `inputs` under the current working directory. When
`GPS_INPUTS_DIR` is set and is not an existing directory, `inputs_dir()` raises
`InputsDirError` naming the variable and path. Load a config with
`Config.from_yaml(inputs_dir() / "config.yaml")`.

---

## Development

### Setup

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
pytest --cov=gps_journey --cov-report=html
```

### Quality Assurance

**Location accuracy** (`tests/unit/test_location_accuracy.py`) checks that
specific local place names are reported rather than a distant city.
`tests/unit/test_geocoding.py` and
`tests/unit/test_nominatim_cache_and_rate_limit.py` check that `Location`
carries `town`/`village`/`hamlet` (kept separate) through both `reverse_geocode`
and the geocoding cache, so rural endpoints resolve to a real settlement instead
of a county-joined `name`.

**Narrative cleanup** (`tests/unit/test_narrative_cleanup.py`) checks content
filtering: no raw GPS coordinates, stop durations or mid-narrative times in
narrative text, and every photo included chronologically.

### Code Quality

```bash
ruff check .
ruff format .
mypy gps_journey/   # optional
```

`ruff.toml` extends `pyproject.toml` and turns on extra rule families
(currently just `TD`, flake8-todos) that the project already passes at zero
findings, a one-way ratchet so those families cannot regress. Add a family to
`extend-select` only after `ruff check . --extend-select <FAMILY> --no-cache`
reports zero findings for it.

---

## Hugo Integration

### Workflow

1. Record a GPS track (Garmin, Strava, phone app) and export it as GPX
2. Run `gps-journey process` to generate journey content
3. Review and edit the generated markdown
4. Commit it to your Hugo site and deploy

### Front matter

The generated markdown is meant to fit a Hugo journey archetype with front matter
along these lines:

```yaml
---
title: "Sample Road Trip"
date: 2030-01-05
trip:
  start_date: "2030-01-05"
  end_date: "2030-01-12"
  duration_days: 8
  distance_km: 640  # Auto-calculated
location:
  coordinates:
    lat: 30.0
    lon: -40.0
---
```

The generator does not write a `gallery:` list. `scripts/process_local_photos.py`
prints a preview of gallery entries for the first five matched photos (`path`,
`thumb`, an optional `location` and `timestamp`) so you can paste it into the
front matter by hand.

---

## API Design Principles

1. **Immutable data models** - journey data is immutable once parsed
2. **Provider abstraction** - geocoding is a protocol, so another service or a test double can be swapped in
3. **Lazy loading** - geocoding only when requested (and cached)
4. **Error recovery** - graceful degradation (missing photos, failed geocoding)
5. **Test-driven** - tests accompany every feature

---

## Documentation

- [QUICKSTART.md](QUICKSTART.md) - a short walkthrough
- [ARCHITECTURE.md](ARCHITECTURE.md) - technical architecture and design patterns
- [CHANGELOG.md](CHANGELOG.md) - release notes

---

## License

MIT License (see `pyproject.toml`).
