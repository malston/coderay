"""The visual layer every renderer shares.

The analyses own different page shapes on purpose -- one page of card rails,
a multi-file reading tour, two hand-built data pages -- but they present the
same product, so the fonts, colour tokens, code typography and third-party
head tags are defined once in crawl.core.theme and included by all of them.
"""
import re

from crawl.analyses.git_history import render as git_history_render
from crawl.analyses.product_intent import render as product_intent_render
from crawl.analyses.tour import render as tour_render
from crawl.core import render, theme


def _tags(html):
    return re.findall(r'<(?:script|link)\b[^>]*cdn\.jsdelivr\.net[^>]*>', html, re.S)


# Every page template that carries a <style> block of its own.
TEMPLATES = {
    "card": render.PAGE,
    "tour/index": tour_render.INDEX_HTML_TEMPLATE,
    "tour/chapter": tour_render.CHAPTER_HTML_TEMPLATE,
    "git-history": git_history_render.HTML_TEMPLATE,
    "product-intent": product_intent_render.HTML_TEMPLATE,
}

# The last slot each template fills in its own right. The dark block has to
# come after it, or a rule written later outranks the dark surface.
LAST_OWN_SLOT = {
    "card": "{rail_widths}",
    "tour/index": "{shared_style}",
    "tour/chapter": "{shared_style}",
    "git-history": "{tokens}",
    "product-intent": "{tokens}",
}


def test_head_assets_loads_the_web_fonts():
    assert "fonts.googleapis.com/css2" in theme.HEAD_ASSETS
    assert "family=Inter" in theme.HEAD_ASSETS
    assert "JetBrains+Mono" in theme.HEAD_ASSETS


def test_head_assets_loads_highlighting_and_diagrams():
    assert "highlight.min.js" in theme.HEAD_ASSETS
    assert "github-dark.min.css" in theme.HEAD_ASSETS
    assert "mermaid.min.js" in theme.HEAD_ASSETS


def test_every_head_asset_from_the_cdn_is_pinned_and_hash_checked():
    tags = _tags(theme.HEAD_ASSETS)
    assert tags, "HEAD_ASSETS loads nothing from the CDN; this test no longer guards it"
    for tag in tags:
        assert "integrity=" in tag, f"no integrity hash on {tag[:120]}"
        assert 'crossorigin="anonymous"' in tag, f"integrity without crossorigin: {tag[:120]}"
        assert re.search(r'@\d+\.\d+\.\d+/', tag), f"floating version: {tag[:120]}"


def test_head_assets_initialises_mermaid_at_strict():
    """coderay-q2r.11 was a P1: 'loose' does not sanitise, and every diagram
    label on these pages is LLM-authored from the target repo's own files."""
    assert "securityLevel: 'strict'" in theme.HEAD_ASSETS
    assert "securityLevel: 'loose'" not in theme.HEAD_ASSETS


def test_tokens_define_the_palette_and_code_typography():
    assert ":root" in theme.TOKENS
    assert "--accent" in theme.TOKENS
    assert "'JetBrains Mono'" in theme.TOKENS
    assert "'Inter'" in theme.TOKENS


def test_every_renderer_takes_the_head_and_the_tokens_from_one_place():
    """One definition, four includes. A copy drifts, and only one gets audited."""
    for label, template in TEMPLATES.items():
        assert "{head_assets}" in template, f"{label} writes its own head"
        assert "{tokens}" in template, f"{label} writes its own palette"
        assert not _tags(template), f"{label} writes its own CDN tag instead of sharing one"


def test_dark_tokens_redefine_the_surface_palette():
    assert "@media (prefers-color-scheme: dark)" in theme.DARK_TOKENS
    for token in ("--bg", "--surface", "--text", "--rule", "--body-text"):
        assert token in theme.DARK_TOKENS, f"{token} keeps its light value in dark mode"


def test_dark_tokens_leave_the_accent_to_each_renderer():
    """Each renderer sets its own --accent; the dark block must not take it
    back, or every page goes the same colour."""
    assert "--accent:" not in theme.DARK_TOKENS


def test_the_dark_block_comes_after_every_rule_it_has_to_outrank():
    """It redefines :root at equal specificity, so order is what decides. A
    renderer's accent or layout rule placed after it would win instead."""
    for label, template in TEMPLATES.items():
        assert "{dark_tokens}" in template, f"{label} has no dark mode"
        assert template.index("{tokens}") < template.index("{dark_tokens}"), label
        assert template.index("{dark_tokens}") > template.rindex(LAST_OWN_SLOT[label]), (
            f"{label} writes rules after the dark block, which would outrank it")


def test_diagrams_follow_the_colour_scheme():
    """A 'neutral' diagram is light artwork; on a dark page it reads as broken."""
    assert "prefers-color-scheme: dark" in theme.HEAD_ASSETS
    assert "'dark' : 'neutral'" in theme.HEAD_ASSETS


# Elements whose colour is fixed by design rather than by the scheme: the hero
# bands, and the saturated chips and bars that carry white text in either one.
SCHEME_INDEPENDENT = (".hero", ".eyebrow", ".gc-bar", ".bar-fill", ".tl-era", ".num")


def _repainted_in_the_dark():
    """Selectors the dark block repaints, which may therefore
    keep a literal value in the light scheme."""
    return {sel.strip() for sel, _ in
            re.findall(r"([.\w-]+)\s*\{([^{}]*background[^{}]*)\}", theme.DARK_TOKENS)}


def test_no_page_hardcodes_a_colour_that_dark_mode_cannot_reach():
    """Ink and surfaces both have to come from tokens.

    A literal light value leaves a bright band on a dark page; a literal dark
    one leaves unreadable text on it. Both have happened here, so the check
    runs on every literal rather than on light ones alone.
    """
    repainted = _repainted_in_the_dark()
    assert repainted, "the dark block repaints nothing; this allowance is stale"
    for label, template in TEMPLATES.items():
        block = re.search(r"<style>(.*?)</style>", template, re.S)
        if not block:
            continue
        # Drop each template's single-brace slots so a rule carrying one still
        # parses as a rule; these templates write literal CSS braces doubled.
        css = re.sub(r"\{([a-z_]+)\}", r"\1", block.group(1))
        for selector, body in re.findall(r"([^{}]+)\{\{([^{}]*)\}\}", css):
            sel = selector.strip()
            # :root declares the tokens; the dark block redefines them there.
            if sel.endswith(":root") or sel in repainted:
                continue
            if any(d in sel for d in SCHEME_INDEPENDENT):
                continue
            literal = re.search(r"(?<!-)\b(color|background(?:-color)?):[^;]*?(#[0-9a-fA-F]{3,6})", body)
            assert not literal, (
                f"{label}: {sel} hardcodes {literal.group(2)} for "
                f"{literal.group(1)}: {' '.join(body.split())}")
