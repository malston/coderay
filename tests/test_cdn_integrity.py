"""Every third-party script and stylesheet must be pinned and hash-checked.

These pages render diagram labels and code the LLM wrote out of the target
repository's own files, and a card page is exactly the artifact someone opens
without reading it first. A CDN that swaps a script would run it with the page.

Google Fonts is deliberately not covered. Its css2 endpoint serves different
@font-face sources per user-agent -- a woff2 URL to a modern browser and a
/l/font?kit= fallback to an old one -- so a single integrity hash would block
the stylesheet for some visitors rather than protect them.
"""
import json
import pathlib
import re

import pytest

from crack.analyses import ANALYSES
from crack.analyses.tour import render as tour_render
from crack.core import render

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden"

# A <script src=...> or <link href=...> pointing at the CDN, attributes and all.
_TAG_RE = re.compile(r'<(?:script|link)\b[^>]*cdn\.jsdelivr\.net[^>]*>', re.S)
_EXACT_VERSION_RE = re.compile(r'@\d+\.\d+\.\d+/')


def _cdn_tags(html):
    return _TAG_RE.findall(html)


def _card_html(name):
    """Render live, not read off disk.

    Reading the committed golden bytes would make this pass against a renderer
    that had lost its integrity attributes entirely, until someone regenerated
    the fixtures. The golden files are checked by test_golden.py; this file has
    to hold the renderer itself.
    """
    shared = json.loads((GOLDEN / name / "shared.json").read_text(encoding="utf-8"))
    return render.render_html(ANALYSES[name], "toy_repo", shared)


def _sources():
    """Every place a CDN tag is written, rendered rather than read."""
    out = {}
    for d in sorted(p for p in GOLDEN.iterdir() if p.is_dir()):
        out[f"card/{d.name}"] = _card_html(d.name)
    # tour's templates carry a {mermaid_script} slot rather than the tag, so
    # compose them the way write_index_html and write_chapter_files do.
    for label, template in (("tour/index", tour_render.INDEX_HTML_TEMPLATE),
                            ("tour/chapter", tour_render.CHAPTER_HTML_TEMPLATE)):
        out[label] = template.replace("{mermaid_script}", tour_render.MERMAID_SCRIPT)
    return out


@pytest.mark.parametrize("label", sorted(_sources()))
def test_every_cdn_resource_is_pinned_and_hash_checked(label):
    html = _sources()[label]
    tags = _cdn_tags(html)
    assert tags, f"{label} loads nothing from the CDN; this test is no longer guarding it"
    for tag in tags:
        assert "integrity=" in tag, f"{label}: no integrity hash on {tag[:120]}"
        assert 'crossorigin="anonymous"' in tag, f"{label}: integrity without crossorigin is ignored: {tag[:120]}"
        assert _EXACT_VERSION_RE.search(tag), (
            f"{label}: floating version, so the hash cannot match for long: {tag[:120]}")


def test_the_card_engine_and_the_tour_agree_on_the_mermaid_build():
    """Two renderers pinning different mermaid builds means two sets of
    diagram-rendering behaviour to reason about, and only one gets audited."""
    def mermaid_pin(html):
        m = re.search(r'mermaid@([\d.]+)/dist/mermaid\.min\.js', html)
        return m.group(1) if m else None

    card = mermaid_pin(_card_html("backend"))
    tour = mermaid_pin(tour_render.MERMAID_SCRIPT)
    assert card is not None and tour is not None
    assert card == tour


def test_the_same_mermaid_build_carries_the_same_hash():
    """A copied-but-stale hash is worse than none: it fails closed on the right
    file. Both renderers pin one build, so both must name one digest."""
    def sri(html):
        return set(re.findall(r'mermaid[^>]*?integrity="([^"]+)"', html, re.S))

    card = sri(_card_html("backend"))
    tour = sri(tour_render.MERMAID_SCRIPT)
    assert card == tour, f"card engine {card} vs tour {tour}"
