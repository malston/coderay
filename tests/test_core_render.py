from crack.core.render import (Section, Theme, card, esc, extract_mermaid, md,
                               md_rich, render_html, render_markdown,
                               split_cards, strip_mermaid)

def test_md_unwraps_a_single_paragraph():
    assert md("hello **world**") == "hello <strong>world</strong>"

def test_md_keeps_multiple_paragraphs_wrapped():
    assert md("one\n\ntwo").startswith("<p>")

def test_md_handles_none():
    assert md(None) == ""

def test_md_rich_turns_a_mermaid_fence_into_a_pre_block():
    out = md_rich("```mermaid\nflowchart LR\n  a --> b\n```")
    assert '<pre class="mermaid">' in out
    assert "language-mermaid" not in out

def test_md_does_not_pass_through_raw_html():
    assert "<script>" not in md("<script>alert(1)</script>")

def test_esc_escapes_and_strips():
    assert esc("  <b>&  ") == "&lt;b&gt;&amp;"

def test_split_cards_splits_on_h3_and_drops_the_preamble():
    assert split_cards("intro\n\n### A\nbody a\n\n### B\nbody b") == [
        ("A", "body a"), ("B", "body b")]

def test_split_cards_of_empty_is_empty():
    assert split_cards("") == []
    assert split_cards(None) == []

def test_extract_and_strip_mermaid_are_complementary():
    text = "before\n\n```mermaid\ngraph TD\n```\n\nafter"
    assert extract_mermaid(text) == "graph TD"
    assert "mermaid" not in strip_mermaid(text)

def test_card_wraps_header_and_body():
    out = card("Title", "body")
    assert '<li class="card">' in out
    assert "Title" in out and "body" in out

# A minimal card-family analysis, standing in for a real one.
def _theme(**over):
    base = dict(
        title_suffix="demo", eyebrow="Demo", accent="#000", accent_soft="#eee",
        hero_from="#111", hero_to="#222", eyebrow_color="#333", eyebrow_bar="#444",
        sub_color="#555", card_top_from="#666",
        subtitle=lambda sh: "sub", footer=lambda sh: "foot",
        md_preamble=lambda sh: "")
    base.update(over)
    return Theme(**base)

class _Analysis:
    SECTIONS = [Section("01", "Only", "note", "rail", 400, "body_md")]
    THEME = _theme()

def test_render_html_builds_a_page_from_sections_and_theme():
    out = render_html(_Analysis, "repo", {"body_md": "### A\ntext"})
    assert "<title>repo: demo</title>" in out
    assert "Only" in out and "foot" in out
    assert ".rail.rail .card { flex: 0 0 400px; width: 400px; }" in out

def test_render_html_escapes_the_page_name():
    out = render_html(_Analysis, "<script>x</script>", {"body_md": "### A\nt"})
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out

def test_render_markdown_emits_a_heading_per_section():
    out = render_markdown(_Analysis, "repo", {"body_md": "### A\ntext"})
    assert out.startswith("# repo: demo\n")
    assert "## Only" in out

def test_when_empty_omit_drops_the_section():
    class A(_Analysis):
        SECTIONS = [Section("01", "Gone", "n", "r", 400, "missing", when_empty="omit")]
    assert "Gone" not in render_html(A, "repo", {})
    assert "Gone" not in render_markdown(A, "repo", {})

def test_when_empty_skip_note_renders_a_head_without_a_rail():
    class A(_Analysis):
        SECTIONS = [Section("01", "Skipped", "n", "r", 400, "missing",
                            when_empty="skip-note", skip_note=lambda sh: "nothing found")]
    out = render_html(A, "repo", {})
    assert "nothing found" in out
    assert '<ul class="rail' not in out

def test_a_custom_renderer_wins_over_the_card_engine():
    class Bespoke:
        render_html = staticmethod(lambda name, shared: "<html>custom</html>")
        render_markdown = staticmethod(lambda name, shared: "# custom")
    assert render_html(Bespoke, "repo", {}) == "<html>custom</html>"
    assert render_markdown(Bespoke, "repo", {}) == "# custom"

def test_section_intro_comes_from_the_overview():
    shared = {"body_md": "### A\nt", "overview": {"intros": {"Only": "the intro"}}}
    assert "the intro" in render_html(_Analysis, "repo", shared)


def test_mermaid_runs_at_security_level_strict():
    """LLM-authored diagram labels must be sanitised by mermaid itself.

    Escaping the diagram into the HTML source is not enough on its own:
    mermaid reads the element back out of textContent, which the browser has
    already decoded to the raw characters. securityLevel decides what happens
    next, and 'loose' does not sanitise. tour has always used 'strict' and the
    card engine now matches it. Deliberate divergence from the port source,
    tracked as coderay-q2r.11 and reproduced by scripts/regen_golden.py.
    """
    import pathlib as _p

    engine = _p.Path(__file__).parent.parent / "src" / "crack" / "core" / "render.py"
    text = engine.read_text(encoding="utf-8")
    assert "securityLevel: 'strict'" in text
    assert "securityLevel: 'loose'" not in text
    # strict ignores htmlLabels, and leaving it set invites the misreading that
    # HTML inside a label is supported.
    assert "htmlLabels" not in text


def test_card_engine_and_tour_agree_on_mermaid_security():
    """The two renderers must not drift apart on this setting again."""
    import pathlib as _p
    import re as _re

    root = _p.Path(__file__).parent.parent / "src" / "crack"
    found = set()
    for path in (root / "core" / "render.py", root / "analyses" / "tour" / "render.py"):
        found |= set(_re.findall(r"securityLevel: '(\w+)'", path.read_text(encoding="utf-8")))
    assert found == {"strict"}, found
