"""The ported analyses must reproduce their source's output byte for byte.

Regenerate a fixture with scripts/regen_golden.py after a deliberate change.
"""
import json
import pathlib

import pytest

from crack.analyses import ANALYSES
from crack.core import render

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden"

@pytest.mark.parametrize("name", ["backend"])
def test_golden_html(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert render.render_html(ANALYSES[name], "toy_repo", shared) == (d / "index.html").read_text(encoding="utf-8")

@pytest.mark.parametrize("name", ["backend"])
def test_golden_markdown(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert render.render_markdown(ANALYSES[name], "toy_repo", shared) == (d / "index.md").read_text(encoding="utf-8")

@pytest.mark.parametrize("name", ["backend"])
def test_golden_html_escapes_injected_markup(name):
    """Every fixture carries injected markup in two places on purpose: a card
    header, and the mermaid diagram source.

    The diagram is the one that bit the port source (see its commit 725b01e).
    A diagram containing </pre><script> closed the pre element and executed
    when the page was opened. Mermaid reads the element's textContent, which
    the browser decodes back, so escaping the source is safe and reversible.
    """
    d = GOLDEN / name
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html.split("</head>", 1)[1]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


@pytest.mark.parametrize("name", ["backend"])
def test_render_escapes_the_diagram_it_is_handed(name):
    """The golden files are static; this re-renders to catch a live regression."""
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert "</pre><script>" in shared["pipeline_diagram"], "fixture lost its payload"
    html = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "</pre><script>" not in html


@pytest.mark.parametrize("name", ["backend"])
def test_render_escapes_a_diagram_inside_a_card_body(name):
    """The golden fixture's mermaid payload sits above the first `###` header,
    so split_cards drops it before it ever reaches md_rich/_mermaidize (see
    split_cards's docstring). This puts the same payload inside a card body
    instead, so it flows through split_cards into md_rich and exercises
    _mermaidize itself, which must not un-escape markdown-it's already-escaped
    fenced content -- not just the hero's esc() call.
    """
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    shared["pipeline_diagram"] = ""  # keep the hero's esc() out of this test
    shared["pipeline_md"] = (
        "### Route\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        "  route --> mw\n"
        "  </pre><script>alert('xss')</script>\n"
        "```\n"
    )
    html = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html
