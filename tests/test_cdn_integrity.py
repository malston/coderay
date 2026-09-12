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

from crawl.analyses import ANALYSES
from crawl.analyses.tour import render as tour_render
from crawl.core import render, theme

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
    # tour's templates carry a {head_assets} slot rather than the tags, so
    # compose them the way write_index_html and write_chapter_files do.
    for label, template in (("tour/index", tour_render.INDEX_HTML_TEMPLATE),
                            ("tour/chapter", tour_render.CHAPTER_HTML_TEMPLATE)):
        out[label] = template.replace("{head_assets}", theme.HEAD_ASSETS)
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


def test_every_renderer_loads_one_mermaid_build_from_the_shared_layer():
    """Two renderers pinning different mermaid builds means two sets of
    diagram-rendering behaviour to reason about, and only one gets audited.

    Every page takes its mermaid tag from the one shared definition, so the
    check is that each carries it exactly once rather than that two copies
    happen to agree -- a copy reintroduced anywhere shows up as a second pin.
    """
    pin = re.compile(r'mermaid@([\d.]+)/dist/mermaid\.min\.js')
    shared = pin.findall(theme.HEAD_ASSETS)
    assert len(shared) == 1, f"shared layer pins {shared}"
    for label, html in sorted(_sources().items()):
        assert pin.findall(html) == shared, f"{label} pins {pin.findall(html)}, shared layer {shared}"


def test_the_shared_mermaid_build_carries_exactly_one_hash():
    """A copied-but-stale hash is worse than none: it fails closed on the right
    file. One build, one digest, on every page that loads it."""
    def sri(html):
        return set(re.findall(r'mermaid[^>]*?integrity="([^"]+)"', html, re.S))

    shared = sri(theme.HEAD_ASSETS)
    # Without this, deleting every integrity attribute leaves two empty sets
    # and the comparison below passes.
    assert len(shared) == 1, f"shared layer names {shared} mermaid integrity hashes"
    for label, html in sorted(_sources().items()):
        assert sri(html) == shared, f"{label} names {sri(html)}, shared layer {shared}"


@pytest.mark.parametrize("label", sorted(_sources()))
def test_every_renderer_initialises_mermaid_at_strict(label):
    """coderay-q2r.11 was a P1: 'loose' does not sanitise, and every diagram
    label on these pages is LLM-authored from the target repo's own files.

    Mermaid reads the element's textContent, which the browser has already
    decoded back to raw characters, so HTML escaping is undone before mermaid
    sees it and securityLevel is what actually decides. Each renderer carries
    its own copy of this line, so each needs checking -- the card engine's fix
    did not reach the bespoke ones.
    """
    html = _sources()[label]
    if "mermaid.initialize" not in html:
        pytest.skip(f"{label} does not initialise mermaid")
    assert "securityLevel: 'strict'" in html
    assert "securityLevel: 'loose'" not in html
