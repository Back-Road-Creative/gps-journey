"""Characterization tests for gps_journey.hugo.generator.

These pin what HugoGenerator produces today (frontmatter keys and order, the body
text, the written file, title and slug rules, photo-mapping lookup) so a pure
restyle of the module can be shown to change nothing. Everything runs against
tmp_path; nothing touches the network.
"""

import json
import logging
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from gps_journey.core.models import (
    DayBreakdown,
    DayStatistics,
    Journey,
    JourneyStatistics,
    Location,
    Photo,
    PhotoGroup,
)
from gps_journey.hugo.generator import HugoGenerator

START = datetime(2029, 6, 1, 8, 0)
END = datetime(2029, 6, 15, 8, 0)
ENNERBY = Location(latitude=52.5, longitude=-9.0, city="Ennerby", country="Ireland")
FAIRHAVEN = Location(latitude=53.0, longitude=-8.5, city="Fairhaven", country="Ireland")
GALLERY = "images/journeys/sample-trip-2030-06"
MAPPING = {"IMG_001.jpg": "001.jpg", "IMG_003.jpg": "003.jpg"}
OVERVIEW = (
    "A 14-day road trip from Ennerby to Fairhaven, spanning 500 km (311 miles) across "
    "varied terrain and cultural regions"
)
STATS_BLOCK = [
    "### Journey Statistics",
    "",
    "- **Distance:** 500.0 km (310.7 miles)",
    "- **Duration:** 14 days",
    "- **Elevation Gain:** 1000 m",
    "- **Average Speed:** 25.0 km/h",
    "",
]


def _stats():
    return JourneyStatistics(
        total_distance_km=500.0,
        total_distance_miles=310.7,
        total_elevation_gain_m=1000.4,
        total_elevation_loss_m=950.0,
        moving_time_seconds=36000,
        stopped_time_seconds=7200,
        average_speed_kmh=25.04,
        max_speed_kmh=90.0,
        min_elevation_m=0.0,
        max_elevation_m=300.0,
    )


def _journey(**overrides):
    values = {
        "start_date": START,
        "end_date": END,
        "start_location": ENNERBY,
        "end_location": FAIRHAVEN,
        "statistics": _stats(),
    }
    values.update(overrides)
    return Journey(**values)


def _group(name, *filenames):
    photos = tuple(Photo(filename=filename, timestamp=START) for filename in filenames)
    return PhotoGroup(location_name=name, latitude=52.0, longitude=-8.0, photos=photos)


def _day(number, *, locations=(), groups=()):
    stats = DayStatistics(
        day_number=number,
        date=date(2029, 6, number),
        distance_km=123.46,
        duration_hours=5.54,
        elevation_gain_m=210.9,
        elevation_loss_m=180.2,
        photo_count=3,
        waypoint_count=50,
        start_time=datetime(2029, 6, number, 8, 0),
        end_time=datetime(2029, 6, number, 17, 0),
    )
    return DayBreakdown(
        statistics=stats,
        waypoints=(),
        photos=(),
        photo_groups=tuple(groups),
        locations_visited=tuple(locations),
        narrative=f"Day {number} narrative.",
        map_file=f"/maps/test-day{number}.html",
        gpx_file=f"/gpx/test-day{number}.gpx",
    )


def _write_mapping(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _split(path):
    """Return (frontmatter dict, body text) of a generated markdown file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head, body = text.split("\n---\n\n", 1)
    return yaml.safe_load(head), body


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A cwd one level below tmp_path, so a sibling directory stays inside tmp_path."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def _static_mapping(workdir):
    """Where the first candidate, <static_dir>/<gallery>, resolves for a configured static dir."""
    return workdir.parent / "site" / "static" / GALLERY / "photo_mapping.json"


def _sibling_mapping(workdir):
    """A mapping in a sibling directory, which is never consulted by default."""
    return workdir.parent / "static" / GALLERY / "photo_mapping.json"


def _local_mapping(workdir):
    """Where the fallback candidate, <gallery>/photo_mapping.json, resolves."""
    return workdir / GALLERY / "photo_mapping.json"


class TestInit:
    def test_defaults(self):
        generator = HugoGenerator()
        assert generator.output_dir == Path(".")
        assert generator.static_dir is None
        assert generator.photo_mapping is None

    def test_static_dir_is_kept_as_a_path(self, tmp_path):
        generator = HugoGenerator(static_dir=str(tmp_path / "static"))
        assert generator.static_dir == tmp_path / "static"
        assert isinstance(generator.static_dir, Path)

    def test_output_dir_string_becomes_a_path(self, tmp_path):
        generator = HugoGenerator(str(tmp_path / "out"))
        assert generator.output_dir == tmp_path / "out"
        assert isinstance(generator.output_dir, Path)


class TestLoadPhotoMapping:
    def test_configured_static_dir_wins(self, workdir):
        _write_mapping(_static_mapping(workdir), {"a.jpg": "static.jpg"})
        _write_mapping(_local_mapping(workdir), {"a.jpg": "local.jpg"})
        generator = HugoGenerator(static_dir=workdir.parent / "site" / "static")
        assert generator._load_photo_mapping(GALLERY) == {"a.jpg": "static.jpg"}

    def test_no_sibling_directory_is_consulted_by_default(self, workdir):
        _write_mapping(_sibling_mapping(workdir), {"a.jpg": "sibling.jpg"})
        _write_mapping(_static_mapping(workdir), {"a.jpg": "static.jpg"})
        assert HugoGenerator()._load_photo_mapping(GALLERY) == {}

    def test_falls_back_to_the_local_gallery_dir(self, workdir):
        _write_mapping(_local_mapping(workdir), MAPPING)
        assert HugoGenerator()._load_photo_mapping(GALLERY) == MAPPING

    def test_unreadable_first_file_warns_and_falls_through(self, workdir, caplog):
        _write_mapping(_static_mapping(workdir), "{not json")
        _write_mapping(_local_mapping(workdir), MAPPING)
        generator = HugoGenerator(static_dir=workdir.parent / "site" / "static")
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.generator"):
            result = generator._load_photo_mapping(GALLERY)
        assert result == MAPPING
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].startswith("Failed to load photo mapping from ")

    def test_only_unreadable_files_give_an_empty_mapping(self, workdir, caplog):
        _write_mapping(_local_mapping(workdir), "{not json")
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.generator"):
            result = HugoGenerator()._load_photo_mapping(GALLERY)
        assert result == {}
        assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.DEBUG]
        assert caplog.records[-1].getMessage() == f"No photo mapping found for {GALLERY}"

    def test_no_mapping_anywhere_gives_an_empty_mapping(self, workdir, caplog):
        with caplog.at_level(logging.DEBUG, logger="gps_journey.hugo.generator"):
            result = HugoGenerator()._load_photo_mapping(GALLERY)
        assert result == {}
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (logging.DEBUG, f"No photo mapping found for {GALLERY}")
        ]


class TestGenerate:
    def test_writes_into_a_nested_output_dir_with_auto_title_and_slug(self, tmp_path):
        out = tmp_path / "content" / "journeys"
        generator = HugoGenerator(out)
        journey = _journey()

        result = generator.generate(journey)

        target = out / "ennerby-to-fairhaven-road-trip.md"
        assert result == str(target)
        assert [p.name for p in out.iterdir()] == ["ennerby-to-fairhaven-road-trip.md"]
        frontmatter, body = _split(target)
        assert frontmatter == generator._build_frontmatter(
            journey, "Ennerby to Fairhaven Road Trip", "ennerby-to-fairhaven-road-trip", None
        )
        assert frontmatter["featured_image"] == "images/featured/ennerby-to-fairhaven-road-trip.jpg"
        assert "gallery_path" not in frontmatter
        assert body == generator._build_body(journey)
        assert body.startswith(f"## Journey Overview\n\n{OVERVIEW}.\n\n### Journey Statistics\n")
        assert body.endswith("<!--more-->\n")

    def test_photo_mapping_is_empty_without_a_gallery(self, tmp_path):
        generator = HugoGenerator(tmp_path)
        generator.generate(_journey())
        assert generator.photo_mapping == {}

    def test_explicit_title_slug_journey_id_and_gallery(self, tmp_path, workdir):
        _write_mapping(_local_mapping(workdir), MAPPING)
        day = _day(
            1, locations=("Ennerby",), groups=(_group("Ennerby", "IMG_001.jpg", "IMG_002.jpg"),)
        )
        generator = HugoGenerator(tmp_path / "out")

        result = generator.generate(
            _journey(daily_breakdowns=(day,)),
            title="Custom Title",
            slug="custom-slug",
            journey_id="sample-trip-2030-06",
            gallery_path=GALLERY,
        )

        target = tmp_path / "out" / "custom-slug.md"
        assert result == str(target)
        assert generator.photo_mapping == MAPPING
        frontmatter, _body = _split(target)
        assert frontmatter["title"] == "Custom Title"
        assert frontmatter["featured_image"] == "images/featured/sample-trip-2030-06.jpg"
        assert frontmatter["gallery_path"] == GALLERY
        assert frontmatter["days"][0]["photos"] == [
            {"location": "Ennerby", "photos": ["001.jpg", "IMG_002.jpg"]}
        ]

    def test_slug_is_derived_from_a_custom_title(self, tmp_path):
        result = HugoGenerator(tmp_path).generate(_journey(), title="My Trip: Part 1")
        assert result == str(tmp_path / "my-trip-part-1.md")


class TestGenerateTitle:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"title": "Custom Title"}, "Custom Title"),
            ({}, "Ennerby to Fairhaven Road Trip"),
            ({"end_location": ENNERBY}, "Ennerby Journey"),
            (
                {
                    "start_location": Location(latitude=46.9, longitude=-110.4, state="Montana"),
                    "end_location": Location(latitude=43.0, longitude=-107.5, state="Wyoming"),
                },
                "Montana to Wyoming Road Trip",
            ),
            (
                {
                    "start_location": Location(latitude=46.9, longitude=-110.4, state="Montana"),
                    "end_location": Location(latitude=47.0, longitude=-110.0, state="Montana"),
                },
                "Montana Journey",
            ),
            (
                {"end_location": Location(latitude=1.0, longitude=2.0, country="Ireland")},
                "Ennerby Journey",
            ),
            (
                {"start_location": Location(latitude=1.0, longitude=2.0, country="Ireland")},
                "Journey June 2029",
            ),
            ({"end_location": None}, "Journey June 2029"),
            ({"start_location": None}, "Journey June 2029"),
        ],
    )
    def test_title_rules(self, overrides, expected):
        assert HugoGenerator()._generate_title(_journey(**overrides)) == expected


class TestGenerateSlug:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Ennerby to Fairhaven Road Trip", "ennerby-to-fairhaven-road-trip"),
            ("Sample Road Trip, June 2030!", "sample-road-trip-june-2030"),
            ("My Trip: Part 1", "my-trip-part-1"),
        ],
    )
    def test_slug_rules(self, title, expected):
        assert HugoGenerator()._generate_slug(title) == expected


class TestBuildFrontmatter:
    def test_full_journey_without_days(self):
        frontmatter = HugoGenerator()._build_frontmatter(
            _journey(), "Ennerby to Fairhaven Road Trip"
        )
        assert frontmatter == {
            "title": "Ennerby to Fairhaven Road Trip",
            "date": "2029-06-01",
            "author": "Go Move Shift",
            "draft": False,
            "categories": ["Journeys"],
            "tags": [],
            "description": "A 14-day journey",
            "summary": "A 14-day journey covering 500 km",
            "featured_image": "images/featured/ennerby-to-fairhaven-road-trip.jpg",
            "featured_image_alt": "Ennerby to Fairhaven Road Trip",
            "location": {
                "name": "Ennerby",
                "country": "Ireland",
                "coordinates": {"lat": 52.5, "lon": -9.0},
            },
            "trip": {
                "start_date": "2029-06-01",
                "end_date": "2029-06-15",
                "duration_days": 14,
                "distance_km": 500.0,
            },
            "featured": False,
            "toc": True,
        }
        assert list(frontmatter) == [
            "title",
            "date",
            "author",
            "draft",
            "categories",
            "tags",
            "description",
            "summary",
            "featured_image",
            "featured_image_alt",
            "location",
            "trip",
            "featured",
            "toc",
        ]

    def test_featured_image_follows_the_given_slug(self):
        frontmatter = HugoGenerator()._build_frontmatter(
            _journey(), "Any Title", "sample-trip-2030-06"
        )
        assert frontmatter["featured_image"] == "images/featured/sample-trip-2030-06.jpg"
        assert frontmatter["featured_image_alt"] == "Any Title"

    def test_gallery_path_sits_between_the_image_and_the_location(self):
        frontmatter = HugoGenerator()._build_frontmatter(_journey(), "T", "t", GALLERY)
        keys = list(frontmatter)
        assert frontmatter["gallery_path"] == GALLERY
        assert keys.index("featured_image_alt") + 1 == keys.index("gallery_path")
        assert keys.index("gallery_path") + 1 == keys.index("location")

    def test_without_statistics_summary_is_empty_and_distance_is_absent(self):
        frontmatter = HugoGenerator()._build_frontmatter(_journey(statistics=None), "T", "t")
        assert frontmatter["summary"] == ""
        assert "distance_km" not in frontmatter["trip"]

    def test_custom_description_replaces_the_default(self):
        journey = _journey(description="Two weeks on the road")
        assert HugoGenerator()._build_frontmatter(journey, "T", "t")["description"] == (
            "Two weeks on the road"
        )

    def test_location_falls_back_to_state_and_rounds_coordinates(self):
        start = Location(
            latitude=46.87654, longitude=-110.43219, state="Montana", country="United States"
        )
        frontmatter = HugoGenerator()._build_frontmatter(_journey(start_location=start), "T", "t")
        assert frontmatter["location"] == {
            "name": "Montana",
            "country": "United States",
            "coordinates": {"lat": 46.8765, "lon": -110.4322},
        }

    def test_no_start_location_means_no_location_block(self):
        frontmatter = HugoGenerator()._build_frontmatter(_journey(start_location=None), "T", "t")
        assert "location" not in frontmatter

    def test_daily_breakdowns_become_days_with_mapped_and_normalised_photos(self):
        generator = HugoGenerator()
        generator.photo_mapping = MAPPING
        groups = (
            _group("Ennerby", "IMG_001.jpg", "IMG_002.jpg"),
            _group("Unknown Location", "IMG_003.jpg"),
            _group("51.2500, -7.4250", "IMG_004.jpg"),
        )
        day_one = _day(
            1, locations=("Ennerby", "Abbey Street Car Park", "Fairhaven"), groups=groups
        )
        day_two = replace(_day(2), map_file=None, gpx_file=None)
        journey = _journey(daily_breakdowns=(day_one, day_two))

        frontmatter = generator._build_frontmatter(journey, "T", "t")

        keys = list(frontmatter)
        assert keys.index("trip") + 1 == keys.index("days")
        assert keys.index("days") + 1 == keys.index("featured")
        first, second = frontmatter["days"]
        assert first == {
            "day_number": 1,
            "date": "2029-06-01",
            "day_of_week": "Friday",
            "summary": "Day 1 narrative.",
            "statistics": {
                "distance_km": 123.5,
                "duration_hours": 5.5,
                "elevation_gain_m": 210,
                "elevation_loss_m": 180,
                "photo_count": 3,
            },
            "locations": ["Ennerby", "Fairhaven"],
            "map": "/maps/test-day1.html",
            "gpx_download": "/gpx/test-day1.gpx",
            "photos": [
                {"location": "Ennerby", "photos": ["001.jpg", "IMG_002.jpg"]},
                {"location": "Photos", "photos": ["003.jpg"]},
                {"location": "Photos (Location)", "photos": ["IMG_004.jpg"]},
            ],
        }
        assert second["day_number"] == 2
        assert second["date"] == "2029-06-02"
        assert second["day_of_week"] == "Saturday"
        assert second["locations"] == []
        assert second["photos"] == []
        assert second["map"] is None
        assert second["gpx_download"] is None


class TestBuildBody:
    def test_overview_and_statistics_with_a_photo_count(self):
        photos = tuple(Photo(filename=f"IMG_{n}.jpg", timestamp=START) for n in range(3))
        body = HugoGenerator()._build_body(_journey(photos=photos))
        assert body.split("\n") == [
            "## Journey Overview",
            "",
            f"{OVERVIEW} with 3 photos.",
            "",
            *STATS_BLOCK,
            "<!--more-->",
            "",
        ]

    def test_overview_names_fall_back_to_the_full_location_and_then_the_state(self):
        journey = _journey(
            start_location=Location(
                latitude=54.6, longitude=-8.3, name="Harbourview Head Lighthouse", country="Ireland"
            ),
            end_location=Location(latitude=53.3, longitude=-9.0, state="Westmarch"),
        )
        overview = HugoGenerator()._build_body(journey).split("\n")[2]
        assert overview == (
            "A 14-day road trip from Harbourview Head Lighthouse, Ireland to Westmarch, spanning "
            "500 km (311 miles) across varied terrain and cultural regions."
        )

    def test_without_statistics_the_overview_is_a_plain_sentence(self):
        body = HugoGenerator()._build_body(_journey(statistics=None))
        assert body.split("\n") == [
            "## Journey Overview",
            "",
            "Traveling from **Ennerby, Ireland** to **Fairhaven, Ireland**.",
            "",
            "<!--more-->",
            "",
        ]

    def test_statistics_without_both_locations_skip_the_overview(self):
        body = HugoGenerator()._build_body(_journey(end_location=None))
        assert body.split("\n") == ["## Journey Overview", "", *STATS_BLOCK, "<!--more-->", ""]

    def test_nothing_known_leaves_only_the_heading_and_the_more_marker(self):
        journey = _journey(statistics=None, start_location=None, end_location=None)
        assert HugoGenerator()._build_body(journey) == "## Journey Overview\n\n<!--more-->\n"


class TestNormalizeLocationName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Unknown Location", "Photos"),
            ("51.2500, -7.4250", "Photos (Location)"),
            ("-51.2500,7.4250", "Photos (Location)"),
            ("Ennerby", "Ennerby"),
            ("51.2500", "51.2500"),
            ("Near 51.2500, -7.4250", "Near 51.2500, -7.4250"),
        ],
    )
    def test_rules(self, name, expected):
        assert HugoGenerator()._normalize_location_name(name) == expected


class TestFormatMarkdown:
    def test_wraps_yaml_in_delimiters_and_keeps_key_order(self):
        text = HugoGenerator()._format_markdown({"title": "T", "tags": [], "n": 1}, "BODY\n")
        assert text == "---\ntitle: T\ntags: []\nn: 1\n---\n\nBODY\n"

    def test_unicode_is_written_unescaped(self):
        text = HugoGenerator()._format_markdown({"title": "Café Ennerby"}, "x")
        assert text == "---\ntitle: Café Ennerby\n---\n\nx"
