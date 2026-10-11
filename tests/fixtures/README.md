# Test Fixtures

This directory holds shared test data for GPS Journey. It currently contains
no data files: the tests build their GPX documents, waypoints, photos and
journeys in code (see `tests/conftest.py` and the helpers at the top of each
test module), or write them under pytest's `tmp_path`.

If you add a fixture file here, use a small synthetic track and list it below
so this file stays an accurate description of the directory.

## Trying the CLI on your own GPX file

Point the CLI at any GPX file you have; nothing needs to live in this directory.

```bash
# Validate the GPX file
gps-journey validate path/to/track.gpx

# Process with the full pipeline
gps-journey process path/to/track.gpx --geocode --output sample-trip.md
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=gps_journey --cov-report=html
```
