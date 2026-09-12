"""The visual layer every renderer shares.

The analyses own different page shapes on purpose -- one page of card rails,
a multi-file reading tour, two hand-built data pages -- but they present the
same product, so the fonts, colour tokens, code typography and third-party
head tags are defined once in crawl.core.theme and included by all of them.
"""
import json
import pathlib
import re

import pytest

from crawl.analyses import ANALYSES

from crawl.analyses.git_history import render as git_history_render
from crawl.analyses.product_intent import render as product_intent_render
from crawl.analyses.tour import render as tour_render
from crawl.core import render, theme


def _tags(html):
    """Tags from the CDN whose builds are pinned and hash-checked."""
    return re.findall(r'<(?:script|link)\b[^>]*cdn\.jsdelivr\.net[^>]*>', html, re.S)


def _external_refs(html):
    """Any tag pulling a resource off the network, whatever the host.

    Broader than _tags on purpose. Google Fonts is exempt from integrity
    checking, because its css2 endpoint serves different @font-face sources per
    user-agent and one hash would block the stylesheet for some visitors. That
    is a separate question from whether a renderer declares the font link
    itself, which is what the shared layer exists to stop.
    """
    return re.findall(r'<(?:script|link)\b[^>]*(?:src|href)="https?://[^"]*"[^>]*>',
                      html, re.S)


# Every page template that carries a <style> block of its own.
TEMPLATES = {
    "card": render.PAGE,
    "tour/index": tour_render.INDEX_HTML_TEMPLATE,
    "tour/chapter": tour_render.CHAPTER_HTML_TEMPLATE,
    "git-history": git_history_render.HTML_TEMPLATE,
    "product-intent": product_intent_render.HTML_TEMPLATE,
}

# CSS a template reaches through a slot rather than writing inline. Without
# these the colour scan below reads nothing at all for the tour, whose whole
# stylesheet arrives through {shared_style}.
SLOT_CSS = {
    "tour/index": tour_render.SHARED_STYLE,
    "tour/chapter": tour_render.SHARED_STYLE,
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
    """One definition, five templates. A copy drifts, and only one gets audited."""
    for label, template in TEMPLATES.items():
        assert "{head_assets}" in template, f"{label} writes its own head"
        assert "{tokens}" in template, f"{label} writes its own palette"
        assert not _external_refs(template), (
            f"{label} pulls a resource off the network itself instead of sharing one: "
            f"{_external_refs(template)[0][:90]}")


def test_the_renderer_accent_override_follows_the_shared_tokens():
    """TOKENS carries a default --accent, so an override written above it loses
    and every analysis renders the same blue. Only the docstring said so."""
    for label, template in TEMPLATES.items():
        own = re.search(r":root\s*\{\{?[^}]*--accent:", template)
        if not own:
            continue
        assert template.index("{tokens}") < own.start(), (
            f"{label} sets its --accent before {{tokens}}, so the default wins")


def test_dark_tokens_redefine_the_surface_palette():
    assert "@media (prefers-color-scheme: dark)" in theme.DARK_TOKENS
    for token in ("--bg", "--surface", "--text", "--rule", "--body-text"):
        assert token in theme.DARK_TOKENS, f"{token} keeps its light value in dark mode"


def test_dark_tokens_leave_the_accent_to_each_renderer():
    """Each renderer sets its own --accent; the dark block must not take it
    back, or every page goes the same colour."""
    assert "--accent:" not in theme.DARK_TOKENS


def test_the_dark_block_closes_every_style_sheet():
    """It redefines :root at equal specificity, so order is what decides.

    The invariant is that nothing at all follows it inside <style>: a rule
    written after it, or a slot carrying one, would win instead. Asserting the
    tail is empty checks that directly, rather than naming the slot the block
    has to follow and trusting the name to stay accurate.
    """
    for label, template in TEMPLATES.items():
        assert "{dark_tokens}" in template, f"{label} has no dark mode"
        assert template.index("{tokens}") < template.index("{dark_tokens}"), label
        tail = template.split("{dark_tokens}", 1)[1].split("</style>", 1)[0]
        assert not tail.strip(), (
            f"{label} writes {tail.strip()[:60]!r} after the dark block, which would outrank it")


def test_diagrams_follow_the_colour_scheme():
    """A 'neutral' diagram is light artwork; on a dark page it reads as broken."""
    assert "prefers-color-scheme: dark" in theme.HEAD_ASSETS
    assert "'dark' : 'neutral'" in theme.HEAD_ASSETS


# A colour written out rather than taken from a token. The value side covers
# more than hex on purpose: rgba() and the bare keywords are just as fixed, and
# a light one leaves a bright band on a dark page exactly the same way. The
# property side includes border, because a light rule on a dark surface is the
# same defect drawn thinner.
LITERAL_COLOUR = re.compile(
    r"(?<!-)\b(color|background(?:-color)?|border(?:-color|-top|-bottom|-left|-right)?)"
    r":[^;]*?(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|\b(?:white|black)\b)")

# Elements whose colour is fixed by design rather than by the scheme.
SCHEME_INDEPENDENT = (".hero", ".eyebrow", ".gc-bar", ".bar-fill", ".tl-era", ".num")
# .gc-bar, .tl-era and .num carry white text; .bar-fill is a saturated bar
# with no text of its own.


def test_the_dark_block_only_redefines_tokens():
    """Four renderers share it, so naming any one renderer's selector there
    puts that renderer's layout in everyone's stylesheet. Flipping a token does
    the same work and keeps the module's own boundary honest."""
    body = theme.DARK_TOKENS.split("{", 1)[1]
    selectors = [" ".join(s.split()) for s, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", body)]
    assert selectors, "the dark block declares nothing"
    for sel in selectors:
        assert sel.endswith(":root"), f"the dark block styles {sel!r} rather than a token"


def test_no_page_hardcodes_a_colour_that_dark_mode_cannot_reach():
    """Ink and surfaces both have to come from tokens.

    A literal light value leaves a bright band on a dark page; a literal dark
    one leaves unreadable text on it. Both have happened here, so the check
    runs on every literal rather than on light ones alone.
    """
    for label, template in TEMPLATES.items():
        for sel, body in _rules(label, template):
            # :root declares the tokens; the dark block redefines them there.
            if sel.endswith(":root"):
                continue
            if any(d in sel for d in SCHEME_INDEPENDENT):
                continue
            literal = LITERAL_COLOUR.search(body)
            assert not literal, (
                f"{label}: {sel} hardcodes {literal.group(2)} for "
                f"{literal.group(1)}: {' '.join(body.split())}")


def _rules(label, template):
    """Every CSS rule a template ships, inline or through a slot.

    A template writes its literal braces doubled, because it is formatted; CSS
    reached through a slot is substituted as a value and writes them single.
    """
    block = re.search(r"<style>(.*?)</style>", template, re.S)
    inline = block.group(1) if block else ""
    # Drop the template's own slot names so a rule carrying one still parses.
    inline = re.sub(r"\{([a-z_]+)\}", r"\1", inline)
    found = [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{\{([^{}]*)\}\}", inline)]
    slotted = SLOT_CSS.get(label, "")
    found += [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", slotted)]
    assert len(found) > 10, (
        f"{label}: only {len(found)} rules found, so this check is not reading "
        "the stylesheet -- CSS has probably moved behind a slot")
    return found


def test_flat_ink_matches_the_mix_the_stylesheet_does():
    """The flat value only renders where color-mix is unavailable, so it has to
    land on the same colour the @supports rule would have produced."""
    # 60% of #2563eb toward the light #101828, channel by channel.
    assert theme.flat_ink("#2563eb") == "#1d459d"
    assert theme.INK_MIX == 0.60


def test_flat_ink_accepts_the_three_digit_shorthand():
    """CSS allows #abc, and a Theme is free to use it."""
    assert theme.flat_ink("#000") == theme.flat_ink("#000000")
    assert theme.flat_ink("#fff") == theme.flat_ink("#ffffff")


def _relative_luminance(colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (channel(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _mix(a, b, pct):
    def rgb(c):
        h = c.lstrip("#")
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(
        round(x * pct + y * (1 - pct)) for x, y in zip(rgb(a), rgb(b)))


# Every accent that ships, and the surfaces each has to read on.
ACCENTS = {"architecture": "#d97706", "backend": "#4f46e5", "interfaces": "#0d9488",
           "schema": "#6941c6", "history": "#3b82f6", "product": "#3b82f6",
           "tour": "#0d9488", "default": "#2563eb"}
SCHEMES = {"light": {"bg": "#f7f8fa", "surface": "#ffffff", "text": "#101828", "tint": 0.14},
           "dark": {"bg": "#0b0f19", "surface": "#141a27", "text": "#e6e9ef", "tint": 0.22}}
WCAG_AA = 4.5


@pytest.mark.parametrize("name", sorted(ACCENTS))
def test_every_accent_reads_as_text_in_both_schemes(name):
    """--accent is picked to look right as a bar or a fill, and several land
    under AA as small text: schema is 2.63:1 on the dark surface, architecture
    3.00:1 on the light one. --accent-ink is what the renderers set on text,
    so it is the value that has to clear AA."""
    for scheme, s in SCHEMES.items():
        ink = _mix(ACCENTS[name], s["text"], theme.INK_MIX)
        soft = _mix(ACCENTS[name], s["surface"], s["tint"])
        for surface_name, surface in (("bg", s["bg"]), ("surface", s["surface"]),
                                      ("soft tint", soft)):
            got = _contrast(ink, surface)
            assert got >= WCAG_AA, (
                f"{name} ink {ink} on the {scheme} {surface_name} is {got:.2f}:1")


def test_faint_reads_on_the_dark_surfaces():
    """It carries section notes and footers, which are small."""
    faint = re.search(r"--faint:\s*(#[0-9a-fA-F]{3,6})", theme.DARK_TOKENS).group(1)
    for surface in ("#0b0f19", "#141a27"):
        got = _contrast(faint, surface)
        assert got >= WCAG_AA, f"--faint {faint} on {surface} is {got:.2f}:1"


# coderay-2l9. A diagram the model got wrong used to be removed outright. The
# heading and the legend around it stayed, so the tour index showed a caption
# for artwork that was not there and the card family showed an empty framed
# box. Worse, a reader could not tell a dropped diagram from one the page
# never had, so an incomplete report read as a complete one.
FAILED_CLASS = "diagram-failed"


def test_a_diagram_that_cannot_be_rendered_leaves_a_placeholder():
    """Keeping the element is what closes both holes: the tour's heading and
    legend still bracket something, and the card family's box is not empty."""
    assert "el.remove()" not in theme.HEAD_ASSETS, (
        "a removed element orphans the heading and legend around it")
    assert FAILED_CLASS in theme.HEAD_ASSETS


def test_the_placeholder_text_is_fixed_rather_than_taken_from_the_diagram():
    """The diagram source is LLM output over the target repo. textContent does
    not parse markup, but building the notice out of that source would put it
    one refactor away from a sink that does."""
    marker = re.search(r"textContent\s*=\s*(.+)", theme.HEAD_ASSETS)
    assert marker, "nothing sets the placeholder text"
    assert re.match(r"""['"][^'"]+['"];""", marker.group(1).strip()), (
        f"placeholder text is not a literal: {marker.group(1).strip()[:60]}")


def test_the_failed_block_stops_being_a_diagram():
    """It must not keep the mermaid class, or a later pass would try to render
    the placeholder text as a diagram."""
    swap = re.search(r"className\s*=\s*['\"]([\w-]+)['\"]", theme.HEAD_ASSETS)
    assert swap, "the failed block keeps whatever classes it had"
    assert "mermaid" not in swap.group(1)


def test_the_placeholder_is_styled_by_the_shared_layer():
    """One policy for every renderer, so the notice cannot look like four
    different things."""
    assert f".{FAILED_CLASS}" in theme.TOKENS


def test_every_renderer_reaches_the_same_placeholder():
    """coderay-2l9 settled that the tour does not get its own policy. Each
    renderer takes the bootstrap from the shared layer, so none of them can
    quietly choose differently."""
    for label, template in TEMPLATES.items():
        assert "{head_assets}" in template, f"{label} does not take the shared bootstrap"
        assert "el.remove()" not in template, f"{label} drops diagrams on its own terms"


# Everything above reads templates and constants. These read what a browser
# would actually receive, because a template can carry every slot and still
# ship a page with the slot filled empty -- the golden fixtures would catch
# that, but a golden is a change-detector, so a regeneration blesses it.
RENDERED = pathlib.Path(__file__).parent / "fixtures" / "golden"


def _rendered_pages():
    pages = {}
    for d in sorted(p for p in RENDERED.iterdir() if p.is_dir()):
        shared = json.loads((d / "shared.json").read_text(encoding="utf-8"))
        pages[d.name] = render.render_html(ANALYSES[d.name], "toy_repo", shared)
    return pages


@pytest.mark.parametrize("name", sorted(p.name for p in RENDERED.iterdir() if p.is_dir()))
def test_every_rendered_page_ships_the_shared_layer(name):
    """Rendered live rather than read off disk, so it holds the renderer itself
    rather than the bytes someone last regenerated."""
    shared = json.loads((RENDERED / name / "shared.json").read_text(encoding="utf-8"))
    page = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "@media (prefers-color-scheme: dark)" in page, f"{name} ships no dark mode"
    assert "family=Inter" in page, f"{name} ships no web fonts"
    assert "--accent-ink" in page, f"{name} ships no readable accent"
    assert ".diagram-failed" in page, f"{name} ships no placeholder for a failed diagram"


@pytest.mark.parametrize("name", sorted(p.name for p in RENDERED.iterdir() if p.is_dir()))
def test_the_dark_block_is_last_in_every_rendered_page(name):
    """The template order is checked above; this checks it survived rendering,
    since a slot fills with whatever the renderer passes."""
    shared = json.loads((RENDERED / name / "shared.json").read_text(encoding="utf-8"))
    css = re.search(r"<style>(.*?)</style>",
                    render.render_html(ANALYSES[name], "toy_repo", shared), re.S).group(1)
    dark = css.index("@media (prefers-color-scheme: dark)")
    tail = css[dark:]
    # The block's own closing brace, then nothing but whitespace.
    depth, end = 0, None
    for i, ch in enumerate(tail):
        depth += (ch == "{") - (ch == "}")
        if depth == 0 and ch == "}":
            end = i + 1
            break
    assert end, f"{name}: the dark block never closes"
    assert not tail[end:].strip(), (
        f"{name} writes {tail[end:].strip()[:60]!r} after the dark block")
