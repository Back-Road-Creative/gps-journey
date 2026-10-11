"""The accessibility repair applied to every map this service writes.

Folium renders through branca's stock template, and that template emits three
WCAG failures on every single map:

  * `<html>` with no `lang` -- a screen reader announces the page in whatever
    voice it defaults to (WCAG 3.1.1);
  * no `<title>` -- and because these maps are consumed inside an `<iframe>`,
    a frame with no accessible name announces nothing at all (WCAG 2.4.2);
  * `maximum-scale=1.0, user-scalable=no` -- pinch-zoom disabled outright
    (WCAG 1.4.4).

Every map folium writes carries all three. Fixing it where the map is written
is what stops the next map being written broken.

Deliberately free of any folium import: folium is declared in this service's
dependencies but may not be installed in every environment, so the string tests
below do not need it. The repair is a pure string transform over rendered
HTML, and that is exactly what is asserted here.
"""

import re

from gps_journey.visualization.a11y import accessible_html, title_for_slug

# The head folium emits, with the viewport content wrapped across a newline.
# A repair regex that assumes one line silently does nothing here, which is
# the bug this fixture exists to catch.
FOLIUM_HEAD = """<!DOCTYPE html>
<html>
<head>

    <meta http-equiv="content-type" content="text/html; charset=UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>

            <meta name="viewport" content="width=device-width,
                initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
            <style>
                #map_5d45c44b105ad1aa5326d5226cbeecc7 { position: relative; }
            </style>
</head>
<body>
    <div class="folium-map" id="map_5d45c44b105ad1aa5326d5226cbeecc7"></div>
</body>
</html>
"""

TITLE = "Sample Trip 2030-01 — Day 1 route map"


def test_the_page_declares_a_language():
    assert re.search(r"<html[^>]*\slang=[\"']en[\"']", accessible_html(FOLIUM_HEAD, TITLE))


def test_the_page_carries_the_title_it_was_given():
    out = accessible_html(FOLIUM_HEAD, TITLE)
    assert f"<title>{TITLE}</title>" in out


def test_the_reader_can_zoom():
    """The whole point of WCAG 1.4.4: low-vision readers enlarge the page."""
    out = accessible_html(FOLIUM_HEAD, TITLE)
    viewport = re.search(r'<meta name="viewport" content="([^"]*)"', out, re.S).group(1)
    assert "user-scalable=no" not in viewport
    assert "maximum-scale" not in viewport
    assert "width=device-width" in viewport, f"the useful directives were dropped: {viewport!r}"


def test_a_title_with_markup_characters_is_escaped():
    """Journey slugs are user data; an unescaped `&` breaks the head."""
    out = accessible_html(FOLIUM_HEAD, 'Tom & "Jerry" route map')
    assert "<title>Tom &amp; &quot;Jerry&quot; route map</title>" in out


def test_an_already_accessible_page_is_left_alone():
    """Idempotent: re-running the repair must not stack a second title or lang."""
    once = accessible_html(FOLIUM_HEAD, TITLE)
    assert accessible_html(once, TITLE) == once


def test_titles_follow_one_derivation_from_the_file_name():
    """One derivation, so a regenerated map keeps the name its file already had."""
    assert (
        title_for_slug("sample-trip-2030-01-enhanced-day1")
        == "Sample Trip 2030-01 — Day 1 route map"
    )
    assert title_for_slug("sampletrip2030-01") == "Sampletrip 2030-01 route map"
    assert title_for_slug("coast-loop-enhanced-day12") == "Coast Loop — Day 12 route map"


def test_the_generator_never_saves_a_map_around_the_repair():
    """Anti-rot: a new `.save()` call site would ship broken maps again.

    Source-level rather than behavioural because executing the generator needs
    a real journey and a tile fetch; this asserts the one property that matters
    -- that `_save_accessible` is the only door to disk. Add a second
    `map_obj.save(...)` anywhere else and this goes red.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "gps_journey/visualization/map_generator.py"
    tree = ast.parse(src.read_text())

    savers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "save"
            ):
                savers.add(node.name)

    assert savers == {"_save_accessible"}, (
        "a map is being written outside the accessibility repair; route it "
        f"through _save_accessible so the page gets lang/title/zoom: {sorted(savers)}"
    )


def test_a_real_folium_map_comes_out_accessible(tmp_path):
    """End-to-end over the actual renderer, because the fixture above is a copy.

    Folium's template is a dependency that can change under us; if a future
    version renders the head differently the string repair could silently stop
    matching, and the only thing that notices is a check against real output.
    No network: Folium emits CDN URLs, it does not fetch them.
    """
    import folium

    from gps_journey.visualization.map_generator import _save_accessible

    out = tmp_path / "sample-trip-2030-01-enhanced-day1.html"
    _save_accessible(folium.Map(location=(53.3, -6.2), zoom_start=8), out)
    rendered = out.read_text()

    assert re.search(r"<html[^>]*\slang=[\"']en[\"']", rendered)
    assert f"<title>{TITLE}</title>" in rendered
    viewport = re.search(r'<meta name="viewport" content="([^"]*)"', rendered, re.S).group(1)
    assert "user-scalable=no" not in viewport and "maximum-scale" not in viewport
