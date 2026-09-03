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

# git-history and product-intent build their pages from structured data rather
# than markdown blobs and carry no top-level diagram key, so they join the
# byte-for-byte checks but not the diagram-payload ones; each has its own
# payload guard and live escape test below.
GOLDEN_ANALYSES = sorted(DIAGRAM_KEY) + ["git-history", "product-intent"]
DIAGRAM_ANALYSES = sorted(DIAGRAM_KEY)

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

@pytest.mark.parametrize("name", DIAGRAM_ANALYSES)
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


@pytest.mark.parametrize("name", DIAGRAM_ANALYSES)
def test_render_escapes_the_diagram_it_is_handed(name):
    """The golden files are static; this re-renders to catch a live regression."""
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert "</pre><script>" in shared[DIAGRAM_KEY[name]], "fixture lost its payload"
    html = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "</pre><script>" not in html


@pytest.mark.parametrize("name", DIAGRAM_ANALYSES)
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


def test_the_git_history_fixture_still_carries_its_payload():
    """Fixture guard, not escaping coverage (see the card-family twin above).
    The payload sits in a contributor name, a bar note, and an era diagram,
    so the cast/mood bars and _mermaid_block are all exercised by the
    byte-for-byte test; a regenerated fixture that lost them would hollow
    that out silently (coderay-q2r.42)."""
    d = GOLDEN / "git-history"
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    names = [c["name"] for p in shared["profiles"] for c in p["profile"]["cast"]["contributors"]]
    assert any("<script>" in n for n in names), "fixture lost its contributor payload"
    assert "</pre><script>" in shared["eras"][0]["diagram"], "fixture lost its diagram payload"
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


def test_git_history_render_escapes_every_slot_it_is_handed():
    """Live re-render: the bespoke renderer has no card engine behind it, so
    its own _esc, md and _mermaid_block are the only thing between a hostile
    era name, contributor, note, grave entry or diagram and the page."""
    d = GOLDEN / "git-history"
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    payload = "</pre><script>alert(1)</script>"
    shared["eras"][1]["name"] = payload
    shared["eras"][1]["description"] = payload
    shared["eras"][1]["turning_point"] = payload
    shared["profiles"][1]["era"] = shared["eras"][1]
    shared["profiles"][1]["profile"]["cast"]["contributors"][0]["note"] = payload
    shared["profiles"][1]["profile"]["mood"]["patterns"][0]["label"] = payload
    shared["profiles"][1]["profile"]["mood"]["narrative"] = payload
    shared["graves"][0]["commit"]["scope"] = payload
    shared["graves"][0]["entry_md"] = f"text\n\n```mermaid\nflowchart LR\n  A[{payload}]\n```\n"
    shared["overview"]["welcome"] = payload
    html = render.render_html(ANALYSES["git-history"], payload, shared)
    body = html.split("</head>", 1)[1]
    assert "<script>" not in body
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in body


def test_git_history_render_survives_a_skipped_era_and_a_grave_outside_every_era():
    """coderay-q2r.39 lets ProfileEras skip an era with no commits, and
    coderay-q2r.40 lets _era_for return None, so profiles may be fewer than
    eras and a grave may carry an empty era. Neither may shift a profile onto
    the wrong era card or crash the page."""
    d = GOLDEN / "git-history"
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    ghost = {"name": "Ghost era", "start": "2010-01", "end": "2010-12",
             "description": "d", "turning_point": "t"}
    shared["eras"] = [shared["eras"][0], ghost, shared["eras"][1]]   # skipped era in the middle
    shared["graves"][0]["era"] = {}
    html = render.render_html(ANALYSES["git-history"], "toy_repo", shared)
    md = render.render_markdown(ANALYSES["git-history"], "toy_repo", shared)
    assert html.count('<li class="card profile">') == 2
    assert "ERA 3</div>\n          <div class=\"card-name\">Going multi-tenant" in html
    assert "### Era 3: Going multi-tenant" in md
    assert "Ghost era" in html and "Ghost era" in md          # still listed among the eras


def test_the_product_intent_fixture_still_carries_its_payload():
    """Fixture guard, not escaping coverage. Payloads sit in a competitor name
    and a dimension name (_esc), the pain and variant prose (md), and the
    positioning diagram (_html.escape)."""
    d = GOLDEN / "product-intent"
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    assert any("<script>" in c["name"] for c in shared["positioning"]["competitors"])
    assert any("<script>" in dim["name"] for dim in shared["positioning"]["dimensions"])
    assert "</pre><script>" in shared["positioning"]["diagram"]
    assert "<script>" in shared["pain"]
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


def test_product_intent_render_escapes_every_slot_it_is_handed():
    """Live re-render through the bespoke renderer's own _esc, md, md_block
    and the diagram escape."""
    d = GOLDEN / "product-intent"
    shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
    payload = "</pre><script>alert(1)</script>"
    shared["pain"] = shared["variant"] = payload
    pos = shared["positioning"]
    pos["competitors"][0]["name"] = payload
    pos["competitors"][0]["cells"][0] = {"verdict": payload, "detail": payload}
    pos["dimensions"][0] = {"name": payload, "definition": payload}
    pos["sacrifices"] = [payload]
    pos["gains"] = [payload]
    pos["why_incumbents_cannot_copy"] = payload
    pos["diagram"] = payload
    shared["surprises"]["present"][0] = {"headline": payload, "where": payload, "bet": payload}
    shared["surprises"]["absent"][0] = {"headline": payload, "evidence": payload, "tradeoff": payload}
    html = render.render_html(ANALYSES["product-intent"], payload, shared)
    body = html.split("</head>", 1)[1]
    assert "<script>" not in body
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in body
    render.render_markdown(ANALYSES["product-intent"], payload, shared)  # must not raise
