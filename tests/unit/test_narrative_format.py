"""TDD Tests for Narrative Format - Human Journal Requirements."""

import re
from datetime import datetime, timezone

import pytest

from gps_journey.core.models import Journey, JourneyStatistics, Location, Waypoint


def create_test_journey_with_location(dep_location_name: str, arr_location_name: str) -> Journey:
    """Create test journey with specific start/end locations."""
    start_time = datetime(2031, 5, 19, 15, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2031, 5, 19, 20, 30, 0, tzinfo=timezone.utc)

    waypoints = [
        Waypoint(
            latitude=41.612,
            longitude=-93.318,
            timestamp=start_time,
            elevation=10.0,
            location=Location(
                latitude=41.612,
                longitude=-93.318,
                name=dep_location_name,  # Village name
                county="County Tarrow",
                country="Ireland",
            ),
        ),
        Waypoint(
            latitude=41.587,
            longitude=-93.293,
            timestamp=end_time,
            elevation=40.0,
            location=Location(
                latitude=41.587,
                longitude=-93.293,
                city=arr_location_name,  # City name
                county="County Tarrow",
                country="Ireland",
            ),
        ),
    ]

    return Journey(
        start_date=start_time,
        end_date=end_time,
        waypoints=tuple(waypoints),
        statistics=JourneyStatistics(
            total_distance_km=18.0,
            total_distance_miles=11.2,
            total_elevation_gain_m=300.0,
            total_elevation_loss_m=350.0,
            moving_time_seconds=3600,
            stopped_time_seconds=900,
            average_speed_kmh=18.0,
            max_speed_kmh=50.0,
            min_elevation_m=5.0,
            max_elevation_m=130.0,
        ),
    )


def test_departure_includes_specific_location():
    """
    Narrative MUST start with specific departure location, not coordinates.

    This test will FAIL until JournalWriter is fixed.
    """
    from gps_journey.hugo.journal_writer import JournalWriter

    journey = create_test_journey_with_location("Eastport", "Kilvarra")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # Extract first day's narrative
    lines = narrative.split("\n")
    day_text = "\n".join(lines[5:15])  # Skip headers

    # ASSERT: Must include specific departure location
    assert "We left Eastport" in day_text or "We left from Eastport" in day_text, (
        f"Narrative should mention departure location 'Eastport', got: {day_text}"
    )

    # ASSERT: Must NOT use bare coordinates
    assert "41.612" not in day_text, "Should not use coordinates for departure"

    # ASSERT: Must NOT use only county
    assert "We left County Tarrow at" not in day_text, "Should not use only county name"


def test_arrival_includes_specific_location():
    """Narrative MUST end with specific arrival location."""
    from gps_journey.hugo.journal_writer import JournalWriter

    journey = create_test_journey_with_location("Eastport", "Kilvarra")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # ASSERT: Must mention arrival location
    assert (
        "arriving in Kilvarra" in narrative
        or "arriving at Kilvarra" in narrative
        or "arrived in Kilvarra" in narrative
    ), "Should mention specific arrival location"

    # ASSERT: Must NOT use bare coordinates for arrival
    assert "41.587" not in narrative, "Should not use coordinates for arrival"


def test_narrative_flows_naturally():
    """Narrative MUST read naturally, not like a data dump."""
    from gps_journey.hugo.journal_writer import JournalWriter

    journey = create_test_journey_with_location("Alderford", "Kilvarra")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # ASSERT: Should be paragraph format, not bullet points
    assert "**Departed:**" not in narrative, "Should not use structured headers"
    assert "**Route Statistics:**" not in narrative, "Should be natural prose"

    # ASSERT: Should use narrative language
    assert "We left" in narrative or "We departed" in narrative, "Should use first-person narrative"


def test_unidentified_stops_omitted_from_narrative():
    """Stops without POI names MUST be completely omitted."""
    from gps_journey.hugo.journal_writer import JournalWriter

    journey = create_test_journey_with_location("Kilvarra", "Eastport")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # ASSERT: Should NOT contain bare coordinates
    assert not re.search(r"\d+\.\d+°", narrative), "Should not include any coordinates in narrative"

    # ASSERT: Should NOT mention generic stops
    assert "stopped for" not in narrative or "stopped at" in narrative, (
        "If mentioning stop, must say WHERE"
    )


def test_narrative_without_meaningful_stops():
    """If no POI stops detected, narrative should still be complete."""
    from gps_journey.hugo.journal_writer import JournalWriter

    # Journey with no stops (just start and end)
    journey = create_test_journey_with_location("Kilvarra", "Alderford")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # ASSERT: Should still have complete narrative
    assert "We left Kilvarra" in narrative
    assert "arriving" in narrative or "arrived" in narrative
    assert "Alderford" in narrative

    # ASSERT: Should not have awkward gaps
    assert "stopped" not in narrative.lower() or "no stops" in narrative.lower()


def test_narrative_includes_distance_summary():
    """Narrative MUST include distance and duration summary."""
    from gps_journey.hugo.journal_writer import JournalWriter

    journey = create_test_journey_with_location("Eastport", "Kilvarra")
    writer = JournalWriter()
    narrative = writer.generate(journey)

    # ASSERT: Must include distance
    assert "18" in narrative and "km" in narrative

    # ASSERT: Must include duration (4.4 hours)
    assert "hours" in narrative or "Duration" in narrative
