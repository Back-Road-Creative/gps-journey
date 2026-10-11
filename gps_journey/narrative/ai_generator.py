"""
AI-Powered Narrative Generator for Travel Journeys

Uses Claude AI to generate rich, engaging travel narratives from GPS data,
photos, and route information.
"""

import logging
import re
import shutil
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

# Fabricated weather / atmosphere / hype terms a GPS-derived narrative cannot
# support. Mirrors the prompt's ABSOLUTELY-FORBIDDEN list so a free-form or
# "poetic" narrative can't slip subjective claims past the post-generation gate.
_BLOCKED_NARRATIVE_TERMS = (
    "golden hour",
    "morning light",
    "clearing skies",
    "painted in gold",
    "rocky landscape",
    "breathtaking",
    "stunning",
    "majestic",
    "mind-blowing",
    "mind blowing",
    "jaw-dropping",
    "jaw dropping",
    "hidden gem",
    "once in a lifetime",
    "once-in-a-lifetime",
    "you won't believe",
    "you wont believe",
    "unbelievable",
    "otherworldly",
)


def style_guides(word_count_range: tuple) -> dict[str, str]:
    """Per-style writing guidance injected into the narrative prompt.

    Module level so the invariant "no style guide asks for something
    ``_BLOCKED_NARRATIVE_TERMS`` (or the post-generation gate) forbids" is
    directly testable.
    """
    return {
        "engaging": f"Rich, detailed, publication-quality travel writing ({word_count_range[0]}-{word_count_range[1]} words). Evocative but grounded in the actual route and stops.",
        "minimal": f"Brief, highlights-focused ({word_count_range[0]}-{word_count_range[1]} words). Concise but engaging.",
        "poetic": f"Literary register ({word_count_range[0]}-{word_count_range[1]} words): varied sentence rhythm and precise word choice. Draw the effect from the real place names and the shape of the route, never from anything the data does not state.",
    }


_NARRATIVE_CAP_WORD_RE = re.compile(r"\b([A-Z][a-z]{2,})\b")
_NARRATIVE_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")

# Generic words commonly capitalized at sentence start or that are not place
# names. Kept small — grounding compares against the day's KNOWN locations, so
# only false-positive-prone filler needs listing here.
_NARRATIVE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "our",
        "was",
        "were",
        "for",
        "from",
        "with",
        "this",
        "that",
        "they",
        "then",
        "there",
        "here",
        "after",
        "before",
        "while",
        "when",
        "where",
        "into",
        "over",
        "along",
        "through",
        "around",
        "between",
        "day",
        "days",
        "route",
        "journey",
        "road",
        "trip",
        "north",
        "south",
        "east",
        "west",
        "northern",
        "southern",
        "eastern",
        "western",
        "northwest",
        "northeast",
        "southwest",
        "southeast",
        "county",
        "peninsula",
        "coast",
        "coastal",
        "valley",
        "village",
        "town",
        "area",
        "region",
        "various",
        "locations",
        "location",
        "we",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "morning",
        "afternoon",
        "evening",
        "night",
        "late",
        "early",
        "explored",
        "departed",
        "arrived",
        "traveled",
        "continued",
        "heading",
        "started",
    }
)


def _tokenize_locations(locations) -> set:
    """Lowercased word set from a list of known location strings."""
    words: set = set()
    for loc in locations or []:
        if not loc:
            continue
        for word in re.split(r"[^\w]+", str(loc)):
            cleaned = word.lower()
            if len(cleaned) >= 2:
                words.add(cleaned)
    return words


def validate_narrative(narrative: str, allowed_locations) -> list[str]:
    """Ground + blocklist a generated journal narrative — return issues.

    - Blocklist: fabricated weather / atmosphere / hype terms (case-insensitive).
    - Grounding: every place-like proper noun (capitalized, 3+ letters, not a
      generic word, not sentence-cased filler) must appear in the day's known
      GPS / geocoded locations. A single ungrounded name is an issue.

    Sentence-initial lone capitals ("We departed…") are skipped unless part of a
    multi-word capitalized phrase, so ordinary sentence casing isn't flagged.
    """
    issues: list[str] = []
    lower = narrative.lower()
    for term in _BLOCKED_NARRATIVE_TERMS:
        if term in lower:
            issues.append(f"blocked phrase '{term}'")

    known = _tokenize_locations(allowed_locations)
    for m in _NARRATIVE_CAP_WORD_RE.finditer(narrative):
        word = m.group(1)
        if word.lower() in _NARRATIVE_STOPWORDS:
            continue
        prefix = narrative[: m.start()]
        sentence_initial = prefix.strip() == "" or bool(_NARRATIVE_SENTENCE_END_RE.search(prefix))
        if sentence_initial:
            rest = narrative[m.end() :].lstrip()
            if not re.match(r"[A-Z][a-z]{2,}\b", rest):
                continue
        if word.lower() not in known:
            issues.append(f"ungrounded place name '{word}'")
    return issues


class DayData:
    """Data for a single day of travel."""

    def __init__(
        self,
        date: datetime,
        start_location: str,
        end_location: str,
        distance_km: float,
        duration_hours: float,
        elevation_gain_m: float = 0,
        elevation_loss_m: float = 0,
        waypoint_count: int = 0,
        stops: list[dict] | None = None,
        notable_locations: list[str] | None = None,
    ):
        self.date = date
        self.start_location = start_location
        self.end_location = end_location
        self.distance_km = distance_km
        self.duration_hours = duration_hours
        self.elevation_gain_m = elevation_gain_m
        self.elevation_loss_m = elevation_loss_m
        self.waypoint_count = waypoint_count
        self.stops = stops or []
        self.notable_locations = notable_locations or []


class Photo:
    """Photo data with EXIF information."""

    def __init__(
        self,
        filename: str,
        exif_datetime: datetime | None = None,
        gps_coords: tuple | None = None,
        geocoded_location: str | None = None,
        caption: str | None = None,
    ):
        self.filename = filename
        self.exif_datetime = exif_datetime
        self.gps_coords = gps_coords
        self.geocoded_location = geocoded_location
        self.caption = caption

    def with_caption(self, caption: str) -> "Photo":
        """Return a new Photo with updated caption."""
        return Photo(
            filename=self.filename,
            exif_datetime=self.exif_datetime,
            gps_coords=self.gps_coords,
            geocoded_location=self.geocoded_location,
            caption=caption,
        )


class AINarrativeGenerator:
    """Generate travel narratives using Claude AI."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize the AI narrative generator.

        Narratives are generated through the ``claude`` CLI, not the
        Anthropic API SDK. If the ``claude``
        binary is not found on PATH, generation falls back to a factual,
        data-only narrative.

        Args:
            api_key: Deprecated and ignored. Retained for backward
                compatibility; the ``claude`` CLI authenticates with
                whatever session it is logged in with.
        """
        self.model = "sonnet"  # the CLI's model alias; do not pin a dated model id
        self._claude_available = shutil.which("claude") is not None
        if self._claude_available:
            logger.info(
                f"Initialized AI narrative generator using `claude` CLI (model: {self.model})"
            )
        else:
            logger.warning(
                "`claude` CLI not found on PATH. Falling back to factual narratives. "
                "Install the Claude CLI to enable AI-generated narratives."
            )

    def generate_day_narrative(
        self,
        day_data: DayData,
        photos: list[Photo],
        style: str = "engaging",
        word_count_range: tuple = (200, 400),
    ) -> str:
        """
        Generate rich narrative for a single day.

        Args:
            day_data: GPS waypoints, stops, route, statistics
            photos: Photos taken during this day with EXIF metadata
            style: "engaging" (default) | "minimal" | "poetic"
            word_count_range: Target word count (min, max)

        Returns:
            200-400 word narrative with photo shortcode placeholders
        """
        if not self._claude_available:
            logger.warning("`claude` CLI not available. Returning factual narrative.")
            return self._generate_factual_fallback(day_data, photos)

        prompt = self._build_narrative_prompt(day_data, photos, style, word_count_range)

        narrative = self._run_claude_cli(prompt)
        if narrative is None:
            return self._generate_factual_fallback(day_data, photos)

        # Clean the narrative to remove any forbidden elements
        narrative = self._clean_narrative(narrative)

        # Ground + blocklist the LLM narrative before it can ship. A free-form
        # or "poetic" narrative that hallucinates a place or fabricates weather
        # falls back to the factual, GPS-derived narrative rather than being
        # written straight into the live journal.
        allowed = (
            [day_data.start_location, day_data.end_location]
            + list(day_data.notable_locations)
            + [s.get("location", "") for s in day_data.stops]
            + [p.geocoded_location for p in photos if p.geocoded_location]
        )
        issues = validate_narrative(narrative, allowed)
        if issues:
            logger.warning(
                "AI narrative failed validation (%s); using factual fallback",
                "; ".join(issues[:5]),
            )
            return self._generate_factual_fallback(day_data, photos)

        # Inject ALL photo shortcodes in chronological order
        narrative_with_photos = self._inject_all_photos_chronologically(narrative, photos, day_data)

        return narrative_with_photos

    def _run_claude_cli(self, prompt: str) -> str | None:
        """
        Generate text by piping ``prompt`` to the ``claude -p`` CLI via STDIN.

        STDIN is used (rather than argv) to avoid argument-length limits on
        long prompts. ``temperature``/``max_tokens`` are not settable via
        ``claude -p`` and are intentionally omitted.

        Returns:
            The stripped stdout, or ``None`` on a non-zero exit code, empty
            output, timeout, or any other failure — callers fall back to a
            factual narrative when this returns ``None``.
        """
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", self.model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            logger.error("`claude` CLI timed out generating narrative")
            return None
        except Exception as e:
            logger.error(f"Error invoking `claude` CLI: {e}")
            return None

        if result.returncode != 0:
            logger.error(
                f"`claude` CLI exited with code {result.returncode}: {result.stderr.strip()}"
            )
            return None

        output = result.stdout.strip()
        if not output:
            logger.error("`claude` CLI returned empty output")
            return None

        return output

    def _build_narrative_prompt(
        self,
        day_data: DayData,
        photos: list[Photo],
        style: str,
        word_count_range: tuple,
    ) -> str:
        """Build prompt for AI narrative generation."""

        # Extract key information
        locations_visited = ", ".join(day_data.notable_locations[:5])
        stop_summary = []
        for stop in day_data.stops[:3]:  # Top 3 stops
            location = stop.get("location", f"{stop['lat']:.4f}, {stop['lon']:.4f}")
            duration = stop.get("duration", 0)
            time = stop.get("time", "")
            if time:
                time_str = time.strftime("%H:%M") if hasattr(time, "strftime") else str(time)
                stop_summary.append(f"{location} ({time_str}, {duration} min)")
            else:
                stop_summary.append(f"{location} ({duration} min)")

        # Photo context
        photo_count = len(photos)
        photo_times = [p.exif_datetime.strftime("%H:%M") for p in photos[:5] if p.exif_datetime]
        photo_locations = [p.geocoded_location for p in photos[:3] if p.geocoded_location]

        # Style descriptions
        guides = style_guides(word_count_range)

        prompt = f"""You are a travel writer creating a factual, data-driven daily narrative for a road trip.

**Day Information:**
- Date: {day_data.date.strftime("%A, %B %d, %Y")}
- Route: {day_data.start_location} to {day_data.end_location}
- Distance: {day_data.distance_km:.1f} km
- Duration: {day_data.duration_hours:.1f} hours
- Locations visited: {locations_visited if locations_visited else "Various locations"}

**Key Stops (with actual timestamps):**
{chr(10).join(f"- {s}" for s in stop_summary) if stop_summary else "- No major stops recorded"}

**Photos taken:**
{photo_count} photos at times: {", ".join(photo_times[:5])}{"..." if len(photo_times) > 5 else ""}
{("Key photo locations: " + ", ".join(photo_locations)) if photo_locations else ""}

**Writing Style:** {style}
{guides.get(style, guides["engaging"])}

**Write it this way:**
- First person plural ("we"), past tense.
- Open with the most local departure place name available — village, locality, or townland.
- Name the actual towns and districts driven through. Places carry the narrative; the interest
  comes from specific real detail, not from flourish.
- Prose only — no photo shortcodes.

**Only what the data supports.** Every claim must trace to the day information above, because a
downstream gate rejects the narrative otherwise:
- No weather, light, or mood you were not given ("clearing skies", "morning light",
  "golden hour", "painted in gold", "rocky landscape").
- No activities that are not in the data ("coffee stop", unless it is listed).
- No GPS coordinates ("41.2500°, -93.6000°").
- No stop durations ("9 minutes", "24-minute stop") and no intermediate stop times ("At 10:54 AM
  we stopped"). Departure and arrival times only.

**Illustrative — one acceptable shape, not a template to match:**
"We departed from Westmere (County Tarrow) in the late morning, heading south along the Harbourview Peninsula. The route took us through Alderford and Millbrook before continuing southwest through Kilvarra. We explored the coastal villages of Cliffton and Stonefield before arriving in the Greymoor area by evening."

**Illustrative — a shorter day, same rules:**
"A short hop east from Kenvale, over the Cahmore Pass and down into Glenmara. We stopped in Bantrow before following the harbour road to Skerrick for the night."

**Rejected — invents nothing, but leaks coordinates and stop timings:**
"We departed from Fairhaven city center (41.2500°, -93.6000°) at 7:45 AM. At 8:00 AM we stopped in Tullyvarra for 9 minutes. At 11:37 AM we stopped in Corrabeg for 42 minutes."

Write the factual narrative now:"""

        return prompt

    def _clean_narrative(self, narrative: str) -> str:
        """
        Remove forbidden elements from narrative text.

        Removes:
        - GPS coordinates (e.g., "41.2500°, -93.6000°")
        - Stop durations (e.g., "for 9 minutes", "24-minute stop")
        - Mid-narrative stop times (e.g., "At 10:54 AM we stopped")
        """
        # Remove coordinate patterns (e.g., "41.2500°, -93.6000°" or "(41.2500, -93.6000)")
        narrative = re.sub(r"\(?\d+\.\d+°?,?\s*-?\d+\.\d+°?\)?", "", narrative)

        # Remove duration patterns
        narrative = re.sub(r"\s+for\s+\d+\s+minutes?", "", narrative)
        narrative = re.sub(r"\s+for\s+\d+\s+hours?", "", narrative)
        narrative = re.sub(r"\d+-minute\s+stop", "stop", narrative)
        narrative = re.sub(r"\d+-hour\s+stop", "stop", narrative)
        narrative = re.sub(r"\(\d+\s+min(?:utes?)?\)", "", narrative)
        narrative = re.sub(r",?\s*where we stopped for \d+ minutes", "", narrative)

        # Remove mid-narrative stop times (but preserve departure/arrival context)
        # Remove patterns like "At 10:54 AM we stopped" or "at 2:30 PM we made a stop"
        narrative = re.sub(
            r"[Aa]t\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s+we\s+(?:stopped|made a stop|paused)",
            "We stopped",
            narrative,
        )
        narrative = re.sub(
            r"[Aa]t\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s+we\s+reached", "We reached", narrative
        )

        # Remove standalone time references in the middle of sentences
        narrative = re.sub(r",?\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?(?:\s+we)?", "", narrative)

        # Remove "By X:XX AM/PM" patterns
        narrative = re.sub(r"[Bb]y\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s+", "", narrative)

        # Clean up double spaces and awkward punctuation
        narrative = re.sub(r"\s+", " ", narrative)
        narrative = re.sub(r"\s+,", ",", narrative)
        narrative = re.sub(r",\s*,", ",", narrative)
        narrative = re.sub(r"\.\s*\.", ".", narrative)
        narrative = re.sub(r"\s+\.", ".", narrative)

        return narrative.strip()

    def _inject_all_photos_chronologically(
        self, narrative: str, photos: list[Photo], day_data: DayData
    ) -> str:
        """
        Inject ALL photo shortcodes in chronological order after the narrative.

        This ensures every photo from the day is displayed, sorted by timestamp.
        """
        if not photos:
            return narrative

        # Sort photos by timestamp
        sorted_photos = sorted(photos, key=lambda p: p.exif_datetime or datetime.min)

        # Add all photos after the narrative
        photo_section = "\n\n"
        for photo in sorted_photos:
            shortcode = self._generate_photo_shortcode(photo, day_data)
            photo_section += shortcode + "\n\n"

        return narrative + photo_section

    def _inject_photo_shortcodes(
        self, narrative: str, photos: list[Photo], day_data: DayData
    ) -> str:
        """Inject photo shortcodes at natural break points in narrative."""
        if not photos:
            return narrative

        paragraphs = narrative.split("\n\n")

        # Distribute photos evenly across paragraphs
        photo_positions = self._calculate_photo_positions(len(paragraphs), len(photos))

        result = []
        photo_idx = 0

        for i, para in enumerate(paragraphs):
            result.append(para)

            # Insert photo shortcode after this paragraph?
            if i in photo_positions and photo_idx < len(photos):
                photo = photos[photo_idx]
                shortcode = self._generate_photo_shortcode(photo, day_data)
                result.append(shortcode)
                photo_idx += 1

        return "\n\n".join(result)

    def _calculate_photo_positions(self, num_paragraphs: int, num_photos: int) -> list[int]:
        """Determine which paragraphs should have photos after them."""
        if num_photos == 0:
            return []
        if num_photos >= num_paragraphs:
            # Photo after every paragraph (except last)
            return list(range(num_paragraphs - 1))

        # Distribute evenly
        interval = num_paragraphs / num_photos
        return [int(i * interval) for i in range(1, num_photos + 1)]

    def _generate_photo_shortcode(self, photo: Photo, day_data: DayData) -> str:
        """Generate Hugo shortcode for a photo."""
        time_str = ""
        if photo.exif_datetime:
            time_str = photo.exif_datetime.strftime("%H:%M")

        location_str = photo.geocoded_location or ""

        # Generate caption if not present
        caption = photo.caption
        if not caption and photo.geocoded_location:
            caption = f"Journey photo from {photo.geocoded_location}"
        elif not caption:
            caption = "Journey photo"

        return f'''{{{{< photo-inline
    src="{photo.filename}"
    caption="{caption}"
    time="{time_str}"
    location="{location_str}"
>}}}}'''

    def generate_highlights(self, day_data: DayData) -> list[str]:
        """Generate bullet points of route highlights."""
        highlights = []

        for stop in day_data.stops[:5]:  # Top 5 stops
            time_str = (
                stop["time"].strftime("%H:%M")
                if hasattr(stop.get("time"), "strftime")
                else "Unknown time"
            )
            duration_str = self._format_duration(stop.get("duration", 0))
            location = stop.get("location", "Unknown location")

            highlight = f"**{time_str}** - {location} ({duration_str})"
            highlights.append(highlight)

        return highlights

    def _format_duration(self, minutes: int) -> str:
        """Format duration nicely."""
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        mins = minutes % 60
        if mins > 0:
            return f"{hours}h {mins}min"
        return f"{hours}h"

    def _generate_factual_fallback(self, day_data: DayData, photos: list[Photo]) -> str:
        """Generate factual narrative when AI is unavailable."""
        lines = []

        lines.append(
            f"The journey from {day_data.start_location} to {day_data.end_location} covered {day_data.distance_km:.1f} km over {day_data.duration_hours:.1f} hours."
        )

        if day_data.notable_locations:
            locations = ", ".join(day_data.notable_locations[:3])
            lines.append(f"The route passed through {locations}.")

        if day_data.stops:
            lines.append(f"Notable stops included {len(day_data.stops)} locations along the way.")

        narrative = " ".join(lines)

        # Add ALL photos chronologically
        if photos:
            narrative = self._inject_all_photos_chronologically(narrative, photos, day_data)

        return narrative

    def generate_journey_reflection(
        self, journey_title: str, total_days: int, total_distance_km: float
    ) -> str:
        """Generate a journey reflection/summary paragraph."""
        fallback = f"This {total_days}-day journey covered {total_distance_km:.0f} km through varied landscapes and memorable locations."
        if not self._claude_available:
            return fallback

        prompt = f"""Write a brief, personal reflection on completing a {total_days}-day road trip of {total_distance_km:.0f} km titled "{journey_title}".

**Requirements:**
- One short paragraph
- First person plural ("we")
- Past tense
- Express what made the journey meaningful
- Don't make up specific events - focus on the overall experience"""

        reflection = self._run_claude_cli(prompt)
        if reflection is None:
            return fallback
        return reflection
