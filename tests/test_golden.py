"""The ported analyses must reproduce their source's output byte for byte.

Regenerate a fixture with scripts/regen_golden.py after a deliberate change.
"""
import json
import pathlib

import pytest

from crack.analyses import ANALYSES
from crack.core import render

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden"

# The shared key holding each analysis's mermaid payload. For backend,
# architecture and schema that is what THEME.hero_prefix renders; for
# interfaces it is a section body that Section.prefix renders instead
# (_hero_prefix there draws a bar chart from group_names, no mermaid). Not part
# of the card-family contract either way, so the tests below must be told which
# key to reach for.
DIAGRAM_KEY = {"backend": "pipeline_diagram", "architecture": "arch_diagram",
               "interfaces": "sequence_md", "schema": "erd"}

GOLDEN_ANALYSES = sorted(DIAGRAM_KEY)

@pytest.mark.parametrize("name", GOLDEN_ANALYSES)
def test_golden_html(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert render.render_html(ANALYSES[name], "toy_repo", shared) == (d / "index.html").read_text(encoding="utf-8")

@pytest.mark.parametrize("name", GOLDEN_ANALYSES)
def test_golden_markdown(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert render.render_markdown(ANALYSES[name], "toy_repo", shared) == (d / "index.md").read_text(encoding="utf-8")

@pytest.mark.parametrize("name", GOLDEN_ANALYSES)
def test_the_golden_fixtures_still_carry_their_payload(name):
    """A fixture check, NOT escaping coverage: it reads the committed bytes, so
    no renderer change can fail it.

    What it holds is the payload itself -- a regenerated fixture that quietly
    lost its injected markup would hollow out every live test below. The card
    header payload is only asserted here; the diagram payload is also covered
    live by test_render_escapes_the_diagram_it_is_handed.

    Every fixture carries injected markup in two places on purpose: a card
    header, and the mermaid diagram source.

    The diagram is the one that bit the port source (see its commit 725b01e).
    A diagram containing </pre><script> closed the pre element and executed
    when the page was opened.

    This one reads the committed bytes rather than re-rendering, so it guards
    the fixture, not the renderer: it fails when a regenerated golden file
    loses its payload, which would quietly hollow out every other test here.
    The live escaping is covered by test_render_escapes_* below.

    Escaping the HTML source is necessary but not sufficient on its own.
    Mermaid reads the element's textContent, which the browser has already
    decoded back to the raw characters, so what happens next is decided by
    mermaid's securityLevel. The card engine sets 'strict' (see
    crack/core/render.py and bead coderay-q2r.11, closed), which sanitises.
    """
    d = GOLDEN / name
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html.split("</head>", 1)[1]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


@pytest.mark.parametrize("name", GOLDEN_ANALYSES)
def test_render_escapes_the_diagram_it_is_handed(name):
    """The golden files are static; this re-renders to catch a live regression."""
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert "</pre><script>" in shared[DIAGRAM_KEY[name]], "fixture lost its payload"
    html = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "</pre><script>" not in html


@pytest.mark.parametrize("name", GOLDEN_ANALYSES)
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
    shared[DIAGRAM_KEY[name]] = ""  # keep the other esc() call out of this test
    shared[ANALYSES[name].SECTIONS[0].key] = (
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
