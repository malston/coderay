"""One render engine for the card family, plus the helpers custom renderers reuse.

An analysis either declares THEME + SECTIONS and lets this module build its
page, or defines its own render_html/render_markdown and this module steps
aside. ch05 and ch06 take the second path: their pages are hand-built from
structured data rather than markdown blobs.
"""
import html as _html
import re
from dataclasses import dataclass
from typing import Callable, Optional

from markdown_it import MarkdownIt

_MD = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False}).enable(["table"])

@dataclass(frozen=True)
class Section:
    """One numbered section of a card-family page.

    when_empty controls what happens when shared[key] is falsy:
      "always"    render the section anyway, with an empty rail (the default,
                  matching ch07 01-03, ch09, and ch10)
      "omit"      drop the section entirely (ch08's tour)
      "skip-note" render the head with skip_note() as its note, no rail (ch07 04)
    """
    number: str
    label: str
    note: str
    rail: str
    width: int
    key: str
    when_empty: str = "always"
    skip_note: Optional[Callable] = None
    md_skip_note: Optional[Callable] = None
    prefix: Optional[Callable] = None
    cards: Optional[Callable] = None

@dataclass(frozen=True)
class Theme:
    """The palette and copy that differ per analysis."""
    title_suffix: str
    eyebrow: str
    accent: str
    accent_soft: str
    hero_from: str
    hero_to: str
    eyebrow_color: str
    eyebrow_bar: str
    sub_color: str
    card_top_from: str
    subtitle: Callable
    footer: Callable
    md_preamble: Callable
    hero_prefix: Optional[Callable] = None
    # ch07 titles its page with shared["product_name"] rather than the repo
    # directory name. page_name covers both the HTML hero and the markdown H1.
    page_name: Optional[Callable] = None

def _mermaidize(rendered_html):
    return re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<pre class="mermaid">{m.group(1)}</pre>',
        rendered_html, flags=re.DOTALL,
    )

def md(text):
    if text is None:
        return ""
    out = _MD.render(str(text).strip()).strip()
    if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        return out[3:-4]
    return out

def md_rich(text):
    return _mermaidize(_MD.render(str(text or "").strip()))

def esc(s):
    return _html.escape(str(s).strip())

def extract_mermaid(text):
    m = re.search(r"```mermaid\s*\n(.*?)```", text or "", re.DOTALL)
    return m.group(1).strip() if m else ""

def strip_mermaid(text):
    return re.sub(r"```mermaid\s*\n.*?```", "", text or "", flags=re.DOTALL).strip()

def split_cards(markdown):
    """Split a markdown blob into (header, body) pairs on each `### ` header.

    Content before the first `###` is dropped here; a caller that needs it
    renders it separately through a Section.prefix hook.
    """
    cards, title, body = [], None, []
    for line in (markdown or "").splitlines():
        m = re.match(r'^###\s+(.*)', line)
        if m:
            if title is not None:
                cards.append((title.strip(), "\n".join(body).strip()))
            title, body = m.group(1), []
        elif title is not None:
            body.append(line)
    if title is not None:
        cards.append((title.strip(), "\n".join(body).strip()))
    return cards

def card(header_md, body_md):
    return (
        '      <li class="card">\n'
        f'        <div class="card-top">{md(header_md)}</div>\n'
        f'        <div class="scroll"><div class="card-body">{md_rich(body_md)}</div></div>\n'
        '      </li>'
    )

def section(spec, cards_html, prefix_html="", intro=""):
    intro_html = f'    <div class="sec-intro">{intro}</div>\n' if intro else ""
    return (
        '    <div class="sec-head">\n'
        f'      <span class="sec-n">{spec.number}</span>\n'
        f'      <div class="sec-label">{spec.label}</div>\n'
        f'      <div class="sec-note">{spec.note}</div>\n'
        '      <div class="scroll-hint">swipe &rarr;</div>\n'
        '    </div>\n'
        f'{intro_html}{prefix_html}'
        f'    <ul class="rail {spec.rail}">\n{cards_html}\n    </ul>'
    )

def _skip_head(spec, shared):
    note = spec.skip_note(shared) if spec.skip_note else "skipped"
    return (f'    <div class="sec-head"><span class="sec-n">{spec.number}</span>'
            f'<div class="sec-label">{spec.label}</div>'
            f'<div class="sec-note">{note}</div></div>')

def _intro(shared, label):
    text = (shared.get("overview") or {}).get("intros", {}).get(label, "")
    return md_rich(text) if text else ""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}: {title_suffix}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
  if (window.mermaid) mermaid.initialize({{ startOnLoad: false, theme: 'neutral', securityLevel: 'loose', flowchart: {{ htmlLabels: true }} }});
</script>
<script>
  window.addEventListener('load', async function () {{
    if (window.hljs) {{ try {{ hljs.highlightAll(); }} catch (e) {{}} }}
    if (!window.mermaid) return;
    var blocks = document.querySelectorAll('pre.mermaid');
    for (var i = 0; i < blocks.length; i++) {{
      var el = blocks[i], src = el.textContent;
      try {{
        if ((await mermaid.parse(src, {{ suppressErrors: true }})) === false) {{ el.remove(); continue; }}
        var out = await mermaid.render('mmd' + i, src);
        el.innerHTML = out.svg;
      }} catch (e) {{ el.remove(); }}
    }}
  }});
</script>
<style>
  :root {{
    --bg: #f7f8fa; --surface: #fff; --text: #101828; --muted: #667085;
    --faint: #98a2b3; --rule: #e4e7ec; --line: #eef0f3;
    --accent: {accent}; --accent-soft: {accent_soft}; --good: #16a34a; --stone: #9aa4b2;
    --stone-bg: #f2f4f7; --shadow: 0 1px 2px rgba(16,24,40,.05); --radius: 12px;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 13.5px; line-height: 1.5; background: var(--bg); color: var(--text); margin: 0;
    -webkit-font-smoothing: antialiased; }}
  code, .mono {{ font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace; }}
  main {{ max-width: 1280px; margin: 0 auto; padding: 0 24px 56px; }}

  .hero {{ background: radial-gradient(120% 140% at 50% 0%, {hero_from} 0%, {hero_to} 70%);
    color: #fff; padding: 46px 20px 42px; text-align: center; }}
  .hero-inner {{ max-width: 1120px; margin: 0 auto; }}
  .hero-diagram {{ margin: 18px 0 4px; }}
  .hero-diagram-cap {{ font-size: .7rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
    color: var(--accent); margin: 0 2px 9px; }}
  .eyebrow {{ display: inline-flex; align-items: center; gap: 7px; color: {eyebrow_color};
    font-size: .68rem; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }}
  .eyebrow::before {{ content: ''; width: 16px; height: 2px; background: {eyebrow_bar}; border-radius: 2px; }}
  .hero h1 {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -.025em; margin: 12px 0 10px; }}
  .hero .sub {{ font-size: .94rem; color: {sub_color}; margin: 0 auto; line-height: 1.6; }}

  .sec-head {{ display: flex; align-items: baseline; gap: 10px; margin: 42px 2px 14px; }}
  .sec-n {{ font-family: 'JetBrains Mono', monospace; font-size: .68rem; font-weight: 700; color: var(--accent); }}
  .sec-label {{ display: flex; align-items: center; gap: 9px; font-size: .68rem; font-weight: 700;
    letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }}
  .sec-label::before {{ content: ''; width: 3px; height: 14px; background: var(--accent); border-radius: 2px; }}
  .sec-note {{ font-size: .8rem; color: var(--faint); }}
  .scroll-hint {{ margin-left: auto; font-size: .68rem; font-weight: 600; color: var(--faint); }}

  /* Friendly "start here" welcome + per-section intros */
  .intro {{ background: var(--surface); border: 1px solid var(--rule); border-left: 4px solid var(--accent);
    border-radius: var(--radius); box-shadow: var(--shadow); padding: 20px 24px; margin: 30px 0 4px; }}
  .intro-label {{ font-size: .68rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
    color: var(--accent); margin-bottom: 10px; }}
  .intro p {{ margin: .5em 0; font-size: .96rem; color: #344054; line-height: 1.7; }}
  .intro p:first-child {{ margin-top: 0; }}
  .intro strong {{ color: var(--text); }}
  .sec-intro {{ font-size: .9rem; color: #475467; line-height: 1.6; margin: -4px 2px 12px; }}
  .sec-intro p {{ margin: 0; }}

  .diagram {{ background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 16px; margin-bottom: 16px; overflow-x: auto; }}
  .diagram pre.mermaid {{ margin: 0; text-align: center; background: transparent; }}
  .diagram pre.mermaid svg {{ max-width: 100%; height: auto; }}

  .groupchart {{ background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 16px 20px; display: flex; flex-direction: column; gap: 7px; }}
  .gc-row {{ display: flex; align-items: center; gap: 12px; }}
  .gc-name {{ flex: 0 0 220px; font-size: .82rem; font-weight: 600; color: var(--text); text-align: right;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .gc-track {{ flex: 1; background: var(--stone-bg); border-radius: 5px; overflow: hidden; }}
  .gc-bar {{ height: 22px; background: linear-gradient(90deg, #2dd4bf, var(--accent)); border-radius: 5px;
    color: #fff; font-size: .72rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;
    display: flex; align-items: center; justify-content: flex-end; padding-right: 8px; min-width: 24px; }}
  @media (max-width: 560px) {{ .gc-name {{ flex-basis: 110px; }} }}

  .rail {{ display: flex; gap: 16px; align-items: stretch; overflow-x: auto;
    scroll-snap-type: x proximity; padding: 4px 2px 18px; margin: 0; list-style: none; }}
  .rail::-webkit-scrollbar {{ height: 9px; }}
  .rail::-webkit-scrollbar-track {{ background: var(--line); border-radius: 5px; }}
  .rail::-webkit-scrollbar-thumb {{ background: #cbd2dc; border-radius: 5px; }}
{rail_widths}

  .scroll {{ flex: 1; overflow-y: auto; overscroll-behavior: contain; }}
  .scroll::-webkit-scrollbar {{ width: 9px; }}
  .scroll::-webkit-scrollbar-thumb {{ background: #dce0e7; border-radius: 5px; }}

  .card {{ scroll-snap-align: start; background: var(--surface); border: 1px solid var(--rule);
    border-radius: var(--radius); box-shadow: var(--shadow); border-top: 3px solid var(--accent);
    display: flex; flex-direction: column; overflow: hidden; max-height: 72vh; }}
  .card-top {{ flex-shrink: 0; padding: 14px 18px 12px; border-bottom: 1px solid var(--line);
    background: linear-gradient(180deg, {card_top_from}, #fff); font-weight: 700; font-size: .96rem; line-height: 1.35; }}
  .card-top code {{ font-size: .82em; }}
  .card-body {{ padding: 13px 18px 16px; font-size: .84rem; }}
  .card-body p {{ margin: .5em 0; color: #344054; line-height: 1.6; }}
  .card-body p:first-child {{ margin-top: 0; }}
  .card-body strong {{ color: var(--text); }}
  .card-body em {{ color: var(--muted); }}
  .card-body ul, .card-body ol {{ margin: .5em 0; padding-left: 1.3em; }}
  .card-body li {{ margin: .28em 0; color: #344054; line-height: 1.55; }}

  pre {{ background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 11px 13px; overflow-x: auto; margin: 10px 0; }}
  pre code {{ padding: 0; font-size: .74rem; line-height: 1.5; }}
  pre code.hljs {{ background: transparent; padding: 0; color: #e2e8f0; }}
  code {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: .84em;
    background: var(--stone-bg); color: var(--text); padding: 1px 5px; border-radius: 4px; }}

  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: .78rem; }}
  th, td {{ border: 1px solid var(--rule); padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: var(--stone-bg); font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
  td code {{ font-size: .92em; }}

  footer {{ color: var(--faint); font-size: .74rem; text-align: center; margin-top: 44px;
    padding-top: 18px; border-top: 1px solid var(--rule); }}
  @media (max-width: 560px) {{ .card {{ flex-basis: 86vw !important; width: 86vw !important; }} }}
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <span class="eyebrow">{eyebrow}</span>
      <h1>{name}</h1>
      <p class="sub">{subtitle}</p>
    </div>
  </header>
  <main>
{intro}
{sections}
    <footer>{footer}</footer>
  </main>
</body>
</html>
"""

def _rail_widths(sections):
    return "\n".join(
        f"  .rail.{s.rail} .card {{ flex: 0 0 {s.width}px; width: {s.width}px; }}"
        for s in sections)

def _section_html(spec, shared):
    body = shared.get(spec.key, "")
    if not body:
        if spec.when_empty == "omit":
            return None
        if spec.when_empty == "skip-note":
            return _skip_head(spec, shared)
    builder = spec.cards or (lambda sh, text: "\n".join(card(h, b) for h, b in split_cards(text)))
    prefix = spec.prefix(shared) if spec.prefix else ""
    return section(spec, builder(shared, body), prefix_html=prefix,
                   intro=_intro(shared, spec.label))

def _render_card_page(analysis, name, shared):
    theme = analysis.THEME
    blocks = [html for html in
              (_section_html(spec, shared) for spec in analysis.SECTIONS)
              if html is not None]
    page_name = theme.page_name(shared, name) if theme.page_name else name
    return PAGE.format(
        name=esc(page_name),
        title_suffix=theme.title_suffix,
        eyebrow=esc(theme.eyebrow),
        accent=theme.accent, accent_soft=theme.accent_soft,
        hero_from=theme.hero_from, hero_to=theme.hero_to,
        eyebrow_color=theme.eyebrow_color, eyebrow_bar=theme.eyebrow_bar,
        sub_color=theme.sub_color, card_top_from=theme.card_top_from,
        rail_widths=_rail_widths(analysis.SECTIONS),
        subtitle=theme.subtitle(shared),
        intro=theme.hero_prefix(shared) if theme.hero_prefix else "",
        sections="\n".join(blocks),
        footer=theme.footer(shared),
    )

def _render_card_markdown(analysis, name, shared):
    theme = analysis.THEME
    title = theme.page_name(shared, name) if theme.page_name else name
    parts = [f"# {title}: {theme.title_suffix}\n"]

    preamble = theme.md_preamble(shared)
    if preamble:
        parts.append(preamble)
    welcome = (shared.get("overview") or {}).get("welcome")
    if welcome:
        parts.append(welcome.strip() + "\n")

    for spec in analysis.SECTIONS:
        body = shared.get(spec.key, "")
        if not body and spec.when_empty == "omit":
            continue
        parts.append(f"## {spec.label}\n")
        if not body and spec.md_skip_note:
            parts.append(spec.md_skip_note(shared))
        else:
            # Matches the chapters, which append body.strip() + "\n"
            # unconditionally: an absent key still emits a blank line.
            parts.append(body.strip() + "\n")
    return "\n".join(parts)

def render_html(analysis, name, shared):
    """Render one analysis's page, deferring to a custom renderer when present."""
    custom = getattr(analysis, "render_html", None)
    return custom(name, shared) if custom else _render_card_page(analysis, name, shared)

def render_markdown(analysis, name, shared):
    custom = getattr(analysis, "render_markdown", None)
    return custom(name, shared) if custom else _render_card_markdown(analysis, name, shared)
