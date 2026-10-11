"""Make a rendered Folium map page accessible before it is written to disk.

Folium renders through branca's stock template, and that template is missing
three things on every map it produces:

  * `<html>` carries no `lang`, so assistive tech reads the page in whatever
    voice it happens to default to (WCAG 3.1.1);
  * there is no `<title>`, and these pages are consumed inside an `<iframe>` --
    a frame whose document has no title has no accessible name, so it is
    announced as nothing at all (WCAG 2.4.2);
  * the viewport meta says `maximum-scale=1.0, user-scalable=no`, which turns
    off pinch-zoom for everyone (WCAG 1.4.4).

Repairing the page at write time means downstream accessibility checks need
no exclusion for map pages: every saved map already carries a language, a
title and a zoomable viewport.

Deliberately imports no folium: the transform is pure text over rendered HTML,
which keeps it testable and keeps the rule ("a saved map is an accessible map")
independent of the renderer's internals.
"""

import html as _html
import re

# `<html>` only when it does not already declare a language -- the repair runs
# over its own output during regeneration and must not stack attributes.
_HTML_OPEN = re.compile(r"<html(?![^>]*\blang=)([^>]*)>", re.I)
_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.I)
_HAS_TITLE = re.compile(r"<title\b", re.I)
# re.S is load-bearing: folium wraps this attribute across a newline, and a
# single-line pattern matches nothing while appearing to work.
_VIEWPORT = re.compile(r'(<meta\s+name="viewport"\s+content=")([^"]*)(")', re.I | re.S)
_ZOOM_KILLERS = re.compile(r"\s*,?\s*\b(?:maximum-scale|user-scalable)\s*=\s*[^,\"]*", re.I)

_ALPHA_OR_DIGITS = re.compile(r"[A-Za-z]+|\d+")
_DAY_SUFFIX = re.compile(r"^(.*?)-enhanced-day(\d+)$")


def _zoomable(content: str) -> str:
    """Drop only the directives that forbid zoom; keep width and initial scale."""
    return re.sub(r"\s+", " ", _ZOOM_KILLERS.sub("", content)).strip()


def pretty_slug(slug: str) -> str:
    """`sample-trip-2030-01` -> `Sample Trip 2030-01`, `sampletrip2030-01` -> `Sampletrip 2030-01`.

    Words are capitalised (existing inner capitals kept, so `RockiesMap` is not
    flattened) and a run of adjacent number groups is rejoined with hyphens, so
    a year-month pair reads as a date rather than two loose numbers. Hyphens in
    the slug are not authoritative -- `sampletrip2030-01` splits the same way.
    """
    out: list[str] = []
    for token in _ALPHA_OR_DIGITS.findall(slug):
        if token.isdigit() and out and out[-1][-1].isdigit():
            out[-1] = f"{out[-1]}-{token}"
        else:
            out.append(token if token.isdigit() else token[:1].upper() + token[1:])
    return " ".join(out)


def title_for_slug(stem: str) -> str:
    """The page title for a map file's basename.

    One derivation for every map, so regenerating a journey renames nothing.
    """
    day = _DAY_SUFFIX.match(stem)
    if day:
        return f"{pretty_slug(day.group(1))} — Day {int(day.group(2))} route map"
    return f"{pretty_slug(stem)} route map"


def accessible_html(rendered: str, title: str) -> str:
    """Add the language and title, and re-enable zoom. Idempotent."""
    out = _HTML_OPEN.sub(r'<html lang="en"\1>', rendered, count=1)

    if not _HAS_TITLE.search(out):
        escaped = _html.escape(title, quote=True)
        out = _HEAD_OPEN.sub(lambda m: f"{m.group(0)}\n    <title>{escaped}</title>", out, count=1)

    return _VIEWPORT.sub(lambda m: f"{m.group(1)}{_zoomable(m.group(2))}{m.group(3)}", out)
