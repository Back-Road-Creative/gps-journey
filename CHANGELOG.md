# Changelog

All notable changes to gps-journey are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `gps_journey.config.inputs_dir()` finds the directory for private inputs: `GPS_INPUTS_DIR` if set (it must be an existing directory, else `InputsDirError`), otherwise `inputs` under the current directory.
- GPX parsing, Nominatim geocoding with an on-disk cache, a journey data model, Hugo markdown generation and a command-line interface (`process`, `validate`, `export-metadata`, `version`).
- Photo matching against a GPS track, with explicit uncertainty: `MatchedPhoto.distance_meters` is `None` for a time-only match, `location_status` is `"inferred"` or `"measured"`, and `PublicationPolicy(max_track_gap_seconds=...)` diverts sparse-track matches to `MatchReport.refused`.
- Naive photo timestamps need an explicit `PhotoMatcher(camera_clock=...)`; otherwise they are reported in `MatchReport.needs_clock_decision` instead of being assumed UTC.
- Public helpers `calculate_distance_km` and `calculate_elevation_gain_m` in `gps_journey.analysis.route_analyzer`, and `RouteAnalyzer.get_regions_passed_through`.
- Hugo site locations have no built-in defaults: set `HUGO_CONTENT_PATH` (or `--hugo-dir`) for `export-metadata`, which falls back to `./output/journeys`; `--static-dir` is the only way to give `HugoGenerator` a static directory, and `HUGO_STATIC_PATH` is reserved. A blank value counts as unset. `HugoGenerator` takes an optional `static_dir` argument, and `scripts/process_local_photos.py --hugo-static-dir` defaults to `./output/static`.
- `scripts/generate_narrative.py` (`--gpx`, `--title`, `--output`, `--cache`) writes a day-by-day narrative for a track. Its optional IntelDB recording is off unless `INTEL_DB_PATH` and `INTEL_SCRIPTS_DIR` are both set; `INTEL_PLATFORM` sets the platform label stored with each run (default `gps-journey`). Runs recorded by an earlier version of this script used the default label `gomoveshift-gps`; set `INTEL_PLATFORM=gomoveshift-gps` to keep new runs grouped with that history.

### Fixed
- An empty GPS track reports every photo as unmatched, and a photo/metadata count mismatch raises `ValueError` on an empty track too.
- `RouteAnalyzer.get_towns_passed_through` and `get_road_segments` close a town or road at the last sample that actually returned it, so unnamed or rate-limited samples no longer inflate durations or distances.
