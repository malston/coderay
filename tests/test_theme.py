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
    """A script or link pointing at an absolute http(s) URL, whatever the host.

    Broader than _tags, which sees one CDN. Narrower than every way a page can
    reach the network: an @import or a url() inside a <style> block is not a
    tag and is not covered here.
    """
    return re.findall(r'<(?:script|link)\b[^>]*(?:src|href)="https?://[^"]*"[^>]*>',
                      html, re.S)


# The font stylesheet and the two preconnect hints it needs. Exempt from the
# integrity check below, and only from that one: the css2 endpoint serves
# different @font-face sources per user-agent -- a woff2 URL to a modern
# browser and a /l/font?kit= fallback to an old one -- so a single hash would
# block the stylesheet for some visitors rather than protect them. A preconnect
# opens a connection and fetches nothing, so there is nothing to hash.
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")


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


def test_every_head_asset_is_pinned_and_hash_checked():
    """Every third-party script and stylesheet, whatever the host.

    These pages render diagram labels and code the LLM wrote out of the target
    repository's own files, and one is exactly the artifact someone opens
    without reading it first. A host that swapped a script would run it with
    the page. Checking only the CDN we happen to use today would let a tag
    added from anywhere else ship with no hash at all.
    """
    refs = _external_refs(theme.HEAD_ASSETS)
    assert refs, "HEAD_ASSETS loads nothing; this test no longer guards it"
    checked = 0
    for tag in refs:
        if any(host in tag for host in FONT_HOSTS):
            continue
        checked += 1
        assert "integrity=" in tag, f"no integrity hash on {tag[:120]}"
        assert re.search(r'integrity="sha(?:384|512)-', tag), (
            f"weaker than sha384: {tag[:120]}")
        assert 'crossorigin="anonymous"' in tag, f"integrity without crossorigin: {tag[:120]}"
        assert re.search(r'@\d+\.\d+\.\d+/', tag), f"floating version: {tag[:120]}"
    assert checked, "every head asset was exempted; the allowlist has swallowed the check"


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


def test_the_shared_tokens_open_every_style_sheet():
    """TOKENS carries defaults every renderer is entitled to override, so a
    renderer rule written above it would lose to the default: an --accent
    override above {tokens} makes every analysis render the same blue.

    Asserting that {tokens} opens the block says that for every override at
    once, whether it is written inline or arrives through a slot. Looking for
    the override itself instead misses the tour, whose stylesheet is entirely
    behind {shared_style}.
    """
    for label, template in TEMPLATES.items():
        assert re.search(r"<style>\s*\{tokens\}", template), (
            f"{label} writes rules before {{tokens}}, where the shared defaults would win")


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
    r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch|oklab|lab|lch)\([^)]*\)"
    r"|\b(?:white|black|red|silver|gray|grey|whitesmoke|gainsboro|ivory)\b(?!-)")

# Declarations whose value may name a colour word without painting one.
NOT_A_COLOUR_DECLARATION = ("content", "font", "url(")


def _literal_in(body):
    """The first literal colour in a declaration block, or None.

    Scans values rather than an enumerated property list. Enumerating was
    wrong twice over: it missed background-image, box-shadow, outline and
    every border-*-color longhand, and its lookbehind for custom properties
    happened to blind the same longhands. Skipping --* declarations by name
    and reading whatever is left covers both.
    """
    for declaration in body.split(";"):
        if ":" not in declaration:
            continue
        prop, _, value = declaration.partition(":")
        prop = prop.strip()
        if prop.startswith("--") or any(s in prop for s in NOT_A_COLOUR_DECLARATION):
            continue
        found = LITERAL_COLOUR.search(value)
        if found:
            return prop, found.group(0)
    return None

# Elements whose colour is fixed by design rather than by the scheme.
SCHEME_INDEPENDENT = (".hero", ".eyebrow", ".gc-bar", ".bar-fill", ".tl-era", ".num")
# .gc-bar, .tl-era and .num carry white text; .bar-fill is a saturated bar
# with no text of its own; .hero and .eyebrow sit on a band that is dark in
# both schemes.


def _scheme_independent(selector):
    """Whether a rule is exempt, matching whole class names.

    A substring test reads naturally and exempts far more than it names:
    `.hero` alone would cover `.hero-diagram`, a container for artwork that
    does follow the scheme.
    """
    classes = set(re.findall(r"\.[\w-]+", selector))
    return bool(classes & set(SCHEME_INDEPENDENT))


def test_the_exemptions_all_match_something_that_ships():
    """An entry matching nothing is an exemption nobody can see is stale."""
    live = set()
    for label, template in TEMPLATES.items():
        for sel, _ in _rules(label, template):
            live |= set(re.findall(r"\.[\w-]+", sel))
    unused = sorted(set(SCHEME_INDEPENDENT) - live)
    assert not unused, f"exemptions matching no live selector: {unused}"


def test_the_dark_block_only_redefines_tokens():
    """Four renderers share it, so naming any one renderer's selector there
    puts that renderer's own rule in everyone's stylesheet. Flipping a token
    does the same work and keeps the module's boundary honest."""
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
            if _scheme_independent(sel):
                continue
            literal = _literal_in(body)
            assert not literal, (
                f"{label}: {sel} hardcodes {literal[1]} for "
                f"{literal[0]}: {' '.join(body.split())}")


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


# Tokens whose light value is deliberately kept in the dark scheme. --accent
# and its derivations belong to each renderer and are handled separately;
# --code-fg is the ink on a block that is dark in both; --good and --stone are
# saturated and read on either surface.
LIGHT_VALUE_HOLDS_IN_DARK = {
    "--accent", "--accent-soft", "--accent-ink", "--code-fg", "--good", "--stone",
}


def _tokens_with_a_colour(css):
    """Every custom property in a :root block whose value names a colour."""
    found = {}
    for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", css):
        if re.search(r"#[0-9a-fA-F]{3,8}|rgba?\(|color-mix\(|var\(--", value):
            found[name] = " ".join(value.split())
    return found


def test_every_colour_token_is_answered_by_the_dark_scheme():
    """A token declared light and never redefined ships its light value onto a
    dark page. Naming the ones that matter in a list goes stale the moment a
    token is added; deriving the set from TOKENS does not."""
    light = _tokens_with_a_colour(theme.TOKENS)
    dark = _tokens_with_a_colour(theme.DARK_TOKENS)
    assert light, "no colour tokens found in TOKENS; this check is not reading it"
    missing = sorted(set(light) - set(dark) - LIGHT_VALUE_HOLDS_IN_DARK)
    assert not missing, (
        "these carry a light value into dark mode: "
        + ", ".join(f"{n} ({light[n]})" for n in missing))


def test_the_light_value_allowlist_has_no_stale_entries():
    """An entry naming a token that no longer exists hides the next one."""
    declared = set(_tokens_with_a_colour(theme.TOKENS))
    stale = sorted(LIGHT_VALUE_HOLDS_IN_DARK - declared)
    assert not stale, f"allowlist names tokens TOKENS does not declare: {stale}"


def test_a_diagram_block_does_not_inherit_the_code_block_ink():
    """Until mermaid replaces it, a diagram block holds its own source. The
    shared `pre` rule paints ink meant for the dark code background, so on a
    light surface that source is invisible -- and if mermaid never loaded, no
    placeholder is written either, so the reader gets an empty box."""
    assert re.search(r"pre\.mermaid\s*\{[^}]*color:", theme.TOKENS), (
        "pre.mermaid takes its colour from the pre rule, which is code-block ink")
    assert not re.search(r"pre\.mermaid\s*\{[^}]*color:\s*inherit", theme.TOKENS), (
        "inherit is wrong here: a diagram inside a hero band would inherit white")


def test_every_head_asset_comes_from_a_host_we_chose():
    """A tag from anywhere else would have to be hashed, and the integrity
    check above only knows the hosts it is told about."""
    hosts = {re.search(r"https?://([^/\"]+)", tag).group(1)
             for tag in _external_refs(theme.HEAD_ASSETS)}
    assert hosts == {"fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net"}, (
        f"unexpected host in the shared head: {hosts}")


@pytest.mark.parametrize("label", sorted(TEMPLATES))
def test_each_template_carries_exactly_one_style_block(label):
    """Every CSS check here reads the first block. A second one is the natural
    way round a rule that says nothing may follow the dark block."""
    assert TEMPLATES[label].count("<style>") == 1, (
        f"{label} has more than one style block, so the checks below read only part of it")


# The tour writes multi-file output from its own functions rather than through
# crawl.core.runner, so its pages are not under fixtures/golden and the
# parametrized checks above do not reach them. It is also the renderer whose
# whole stylesheet arrives through a slot, which makes it the likeliest place
# for one to be filled empty -- the failure those checks exist to catch.
def test_the_rendered_tour_ships_the_shared_layer(tmp_path):
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
    from regen_tour_golden import render_into

    render_into(tmp_path)
    pages = sorted(tmp_path.glob("*.html"))
    assert len(pages) >= 3, f"the tour rendered {len(pages)} pages; expected an index and chapters"
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert "@media (prefers-color-scheme: dark)" in html, f"{page.name} ships no dark mode"
        assert "family=Inter" in html, f"{page.name} ships no web fonts"
        assert ".diagram-failed" in html, f"{page.name} ships no placeholder rule"
        assert "--accent-ink" in html, f"{page.name} ships no readable accent"
        css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
        assert css.count("@media (prefers-color-scheme: dark)") == 1
        dark = css.index("@media (prefers-color-scheme: dark)")
        assert not _after_the_block(css[dark:]).strip(), (
            f"{page.name} writes rules after the dark block")


def _after_the_block(css):
    """Whatever follows the first balanced brace group in css."""
    depth = 0
    for i, ch in enumerate(css):
        depth += (ch == "{") - (ch == "}")
        if depth == 0 and ch == "}":
            return css[i + 1:]
    raise AssertionError("the block never closes")


def test_a_code_block_is_neutral_before_highlighting_runs():
    """highlight.js adds .hljs to what it processes, so pre code.hljs only
    applies once it has run. A blocked CDN, a failed hash, or simply the
    interval before the load handler fires leaves the block without it, and
    the inline-code rule then paints a light chip inside the dark pre."""
    neutral = re.search(r"\bpre code \{([^}]*)\}", theme.TOKENS)
    assert neutral, "nothing neutralises pre code independently of .hljs"
    assert "background" in neutral.group(1), (
        "pre code does not clear the inline-code chip background")


def test_the_dark_block_declares_only_custom_properties():
    """Selectors are checked above. A plain declaration inside :root is the
    other way a renderer's own rule reaches everyone's stylesheet."""
    for body in re.findall(r":root\s*\{([^{}]*)\}", theme.DARK_TOKENS):
        for declaration in body.split(";"):
            prop = declaration.partition(":")[0].strip()
            if not prop or prop.startswith("/*"):
                continue
            assert prop.startswith("--"), (
                f"the dark block sets {prop!r}, which is a rule rather than a token")
