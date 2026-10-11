"""
Tests for narrative cleanup - removing coordinates, durations, and times.

These tests ensure that the AI-generated narratives are cleaned to remove
unwanted elements like GPS coordinates, stop durations, and mid-stop times.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from gps_journey.narrative.ai_generator import (
    _BLOCKED_NARRATIVE_TERMS,
    AINarrativeGenerator,
    DayData,
    Photo,
    style_guides,
)


class TestNarrativeCleanup:
    """Tests for the _clean_narrative method."""

    @pytest.fixture
    def generator(self):
        """Create generator without API key (we're testing cleanup, not AI)."""
        return AINarrativeGenerator(api_key=None)

    def test_removes_coordinate_patterns(self, generator):
        """GPS coordinates should be removed from narrative."""
        narrative = "We departed from Fairhaven city center (41.2500°, -93.6000°) at 7:45 AM."
        cleaned = generator._clean_narrative(narrative)

        assert "41.2500" not in cleaned
        assert "-93.6000" not in cleaned
        assert "Fairhaven city center" in cleaned

    def test_removes_coordinates_without_degree_symbol(self, generator):
        """Coordinates without degree symbols should also be removed."""
        narrative = "We departed from location (41.7500, -93.1250) in the morning."
        cleaned = generator._clean_narrative(narrative)

        assert "41.7500" not in cleaned
        assert "-93.1250" not in cleaned

    def test_removes_stop_durations_minutes(self, generator):
        """Stop durations in minutes should be removed."""
        narrative = "We stopped in Tullyvarra for 9 minutes before continuing."
        cleaned = generator._clean_narrative(narrative)

        assert "9 minutes" not in cleaned
        assert "for" not in cleaned or "before" in cleaned
        assert "Tullyvarra" in cleaned

    def test_removes_stop_durations_hours(self, generator):
        """Stop durations in hours should be removed."""
        narrative = "We stopped in Corrabeg for 2 hours exploring the town."
        cleaned = generator._clean_narrative(narrative)

        assert "2 hours" not in cleaned
        assert "Corrabeg" in cleaned

    def test_removes_hyphenated_duration(self, generator):
        """Hyphenated duration patterns like '24-minute stop' should be cleaned."""
        narrative = "We made a 24-minute stop in Mullaghbay."
        cleaned = generator._clean_narrative(narrative)

        assert "24-minute" not in cleaned
        assert "Mullaghbay" in cleaned

    def test_removes_parenthetical_duration(self, generator):
        """Parenthetical durations like '(9 min)' should be removed."""
        narrative = "We stopped at Harbourview Head Lighthouse (9 min) for photos."
        cleaned = generator._clean_narrative(narrative)

        assert "(9 min)" not in cleaned
        assert "Harbourview Head Lighthouse" in cleaned

    def test_removes_mid_narrative_stop_times(self, generator):
        """Mid-narrative stop times like 'At 10:54 AM we stopped' should be cleaned."""
        narrative = "At 10:54 AM we stopped in Cliffton for a break."
        cleaned = generator._clean_narrative(narrative)

        assert "10:54 AM" not in cleaned
        assert "Cliffton" in cleaned
        assert "stopped" in cleaned.lower()

    def test_removes_by_time_patterns(self, generator):
        """'By X:XX AM' patterns should be removed."""
        narrative = "By 8:00 AM we reached Tullyvarra."
        cleaned = generator._clean_narrative(narrative)

        assert "8:00 AM" not in cleaned
        assert "reached" in cleaned
        assert "Tullyvarra" in cleaned

    def test_preserves_location_names(self, generator):
        """Location names should be preserved."""
        narrative = (
            "We traveled from Westmere (41.5000°, -93.4000°) through Harbourview to Kilvarra."
        )
        cleaned = generator._clean_narrative(narrative)

        assert "Westmere" in cleaned
        assert "Harbourview" in cleaned
        assert "Kilvarra" in cleaned

    def test_cleans_double_spaces(self, generator):
        """Double spaces from removed content should be cleaned."""
        narrative = "We stopped in Tullyvarra for 9 minutes and then continued."
        cleaned = generator._clean_narrative(narrative)

        assert "  " not in cleaned

    def test_cleans_awkward_punctuation(self, generator):
        """Awkward punctuation from removed content should be fixed."""
        narrative = "We visited Tullyvarra, (for 9 minutes), then moved on."
        cleaned = generator._clean_narrative(narrative)

        assert ",," not in cleaned
        assert ", ," not in cleaned

    def test_complex_narrative_cleanup(self, generator):
        """Test cleanup of a complex narrative with multiple issues."""
        narrative = """We departed from Kilvarra (41.7500°, -93.1250°) at 9:20 AM for a 150.0 km circuit. At 10:35 AM we stopped in the Harbourview North area (County Tarrow) for 11 minutes, followed by another 8-minute stop at 11:50 AM in Harbourview North. By 1:05 PM we had made a brief 5-minute stop. We arrived back at 6:40 PM."""

        cleaned = generator._clean_narrative(narrative)

        # Should NOT contain
        assert "41.7500" not in cleaned
        assert "-93.1250" not in cleaned
        assert "11 minutes" not in cleaned
        assert "8-minute" not in cleaned
        assert "5-minute" not in cleaned
        assert "10:35 AM we stopped" not in cleaned
        assert "11:50 AM" not in cleaned
        assert "1:05 PM" not in cleaned

        # Should contain
        assert "Kilvarra" in cleaned
        assert "Harbourview North" in cleaned
        assert "County Tarrow" in cleaned


class TestPhotoInjection:
    """Tests for chronological photo injection."""

    @pytest.fixture
    def generator(self):
        return AINarrativeGenerator(api_key=None)

    @pytest.fixture
    def sample_photos(self):
        """Create sample photos with timestamps."""
        return [
            Photo(
                filename="photo-003.jpg",
                exif_datetime=datetime(2031, 5, 15, 14, 30),
                geocoded_location="Harbourview North, County Tarrow",
            ),
            Photo(
                filename="photo-001.jpg",
                exif_datetime=datetime(2031, 5, 15, 10, 15),
                geocoded_location="Westmere, County Tarrow",
            ),
            Photo(
                filename="photo-002.jpg",
                exif_datetime=datetime(2031, 5, 15, 12, 0),
                geocoded_location="Rosscarra, County Tarrow",
            ),
        ]

    @pytest.fixture
    def sample_day_data(self):
        return DayData(
            date=datetime(2031, 5, 15),
            start_location="Westmere, County Tarrow",
            end_location="Kilvarra, County Tarrow",
            distance_km=150.0,
            duration_hours=8.5,
        )

    def test_all_photos_included(self, generator, sample_photos, sample_day_data):
        """All photos should be included in output."""
        narrative = "We explored County Tarrow today."
        result = generator._inject_all_photos_chronologically(
            narrative, sample_photos, sample_day_data
        )

        assert "photo-001.jpg" in result
        assert "photo-002.jpg" in result
        assert "photo-003.jpg" in result

    def test_photos_in_chronological_order(self, generator, sample_photos, sample_day_data):
        """Photos should appear in chronological order by timestamp."""
        narrative = "We explored County Tarrow today."
        result = generator._inject_all_photos_chronologically(
            narrative, sample_photos, sample_day_data
        )

        # Find positions of each photo in result
        pos_001 = result.find("photo-001.jpg")
        pos_002 = result.find("photo-002.jpg")
        pos_003 = result.find("photo-003.jpg")

        # photo-001 (10:15) should come before photo-002 (12:00) before photo-003 (14:30)
        assert pos_001 < pos_002 < pos_003, (
            f"Photos not in chronological order: 001@{pos_001}, 002@{pos_002}, 003@{pos_003}"
        )

    def test_empty_photos_returns_narrative(self, generator, sample_day_data):
        """Empty photo list should just return the narrative unchanged."""
        narrative = "We explored County Tarrow today."
        result = generator._inject_all_photos_chronologically(narrative, [], sample_day_data)

        assert result == narrative

    def test_photo_shortcodes_have_location(self, generator, sample_photos, sample_day_data):
        """Photo shortcodes should include location information."""
        narrative = "We explored."
        result = generator._inject_all_photos_chronologically(
            narrative, sample_photos, sample_day_data
        )

        assert 'location="Westmere, County Tarrow"' in result
        assert 'location="Rosscarra, County Tarrow"' in result
        assert 'location="Harbourview North, County Tarrow"' in result


class TestClaudeCLIInvocation:
    """Narratives are generated via the first-party ``claude -p`` CLI, not the SDK."""

    @pytest.fixture
    def day_data(self):
        return DayData(
            date=datetime(2031, 5, 15),
            start_location="Westmere, County Tarrow",
            end_location="Kilvarra, County Tarrow",
            distance_km=150.0,
            duration_hours=8.5,
        )

    def _available_generator(self):
        """Build a generator that believes the ``claude`` CLI is installed."""
        with patch(
            "gps_journey.narrative.ai_generator.shutil.which",
            return_value="/usr/bin/claude",
        ):
            return AINarrativeGenerator()

    def test_invokes_claude_cli_with_sonnet_model_via_stdin(self, day_data):
        """The prompt is piped to ``claude -p --model sonnet`` over STDIN."""
        generator = self._available_generator()
        completed = MagicMock(
            returncode=0, stdout="We departed from Westmere and drove south.", stderr=""
        )
        with patch(
            "gps_journey.narrative.ai_generator.subprocess.run", return_value=completed
        ) as run:
            result = generator.generate_day_narrative(day_data, [])

        run.assert_called_once()
        args, kwargs = run.call_args
        assert args[0] == ["claude", "-p", "--model", "sonnet"]
        assert "Westmere" in kwargs["input"]  # prompt piped via STDIN, not argv
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 180
        assert "Westmere" in result

    def test_nonzero_returncode_falls_back_to_factual(self, day_data):
        generator = self._available_generator()
        completed = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch("gps_journey.narrative.ai_generator.subprocess.run", return_value=completed):
            result = generator.generate_day_narrative(day_data, [])

        # Factual fallback text (from _generate_factual_fallback)
        assert "150.0 km" in result
        assert "Westmere, County Tarrow" in result
        assert "Kilvarra, County Tarrow" in result

    def test_empty_stdout_falls_back_to_factual(self, day_data):
        generator = self._available_generator()
        completed = MagicMock(returncode=0, stdout="   \n", stderr="")
        with patch("gps_journey.narrative.ai_generator.subprocess.run", return_value=completed):
            result = generator.generate_day_narrative(day_data, [])

        assert "150.0 km" in result

    def test_cli_unavailable_never_invokes_subprocess(self, day_data):
        with patch("gps_journey.narrative.ai_generator.shutil.which", return_value=None):
            generator = AINarrativeGenerator()
        with patch("gps_journey.narrative.ai_generator.subprocess.run") as run:
            result = generator.generate_day_narrative(day_data, [])

        run.assert_not_called()
        assert "150.0 km" in result


class TestStyleGuidesDoNotContradictTheGate:
    """A style guide must never ask for what the prompt and the gate forbid.

    ``validate_narrative`` rejects any narrative containing a
    ``_BLOCKED_NARRATIVE_TERMS`` phrase, and the prompt forbids invented
    weather, light and mood. A style guide that asks for "sensory details and
    mood" therefore instructs the model to produce output the same run throws
    away. Asserts over the real data, so a newly added blocked term is covered
    automatically.
    """

    BANNED_WORDS = ("sensory", "mood", "atmospheric", "weather")

    def _guides(self):
        return style_guides((150, 250))

    def test_no_style_guide_uses_a_blocked_narrative_term(self):
        offenders = [
            (style, term)
            for style, guide in self._guides().items()
            for term in _BLOCKED_NARRATIVE_TERMS
            if term in guide.lower()
        ]
        assert offenders == [], f"style guides invite blocked phrases: {offenders}"

    def test_no_style_guide_asks_for_atmosphere_or_mood(self):
        offenders = [
            (style, word)
            for style, guide in self._guides().items()
            for word in self.BANNED_WORDS
            if word in guide.lower()
        ]
        assert offenders == [], f"style guides ask for un-generatable content: {offenders}"

    def test_every_style_guide_is_reachable_from_the_prompt(self):
        guides = self._guides()
        assert set(guides) == {"engaging", "minimal", "poetic"}
