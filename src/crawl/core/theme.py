"""The visual layer every page template includes.

The analyses own different page shapes on purpose -- the card family renders
one page of horizontal rails from SECTIONS and THEME, the tour writes a
multi-file reading tour, and two analyses hand-build their pages from
structured data -- but they are the same product, so the fonts, the palette,
the code typography and the third-party head tags are defined here once and
included by all four. Layout and type sizes stay with each renderer.

Each template carries a {head_assets}, {tokens} and {dark_tokens} slot, in
that order. These are substituted into a template rather than formatted, so
their braces are literal. TOKENS carries a default --accent; a renderer that
wants its own writes a one-line :root override after it.
"""

HEAD_ASSETS = """<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css"
  integrity="sha384-wH75j6z1lH97ZOpMOInqhgKzFkAInZPPSPlZpYKYTOqsaizPvhQZmAtLcPKXpLyH" crossorigin="anonymous">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"
  integrity="sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
  integrity="sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2" crossorigin="anonymous"></script>
<script>
  // Disable auto-run SYNCHRONOUSLY, before DOMContentLoaded -- otherwise Mermaid
  // renders every diagram itself, and our loop below would re-process the
  // already-rendered SVG and wipe it.
  // 'strict' sanitises LLM-authored diagram labels; see coderay-q2r.11.
  var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  if (window.mermaid) mermaid.initialize({
    startOnLoad: false, theme: prefersDark ? 'dark' : 'neutral', securityLevel: 'strict' });
</script>
<script>
  window.addEventListener('load', async function () {
    // Syntax-highlight code blocks. (Mermaid pres have no <code>, so they're skipped.)
    // The catch keeps a highlighting failure from aborting this listener, which
    // would leave every diagram below unrendered.
    if (window.hljs) {
      try { hljs.highlightAll(); } catch (e) { console.warn('crawl: syntax highlighting failed', e); }
    }
    // Render each diagram, but validate first with parse() so a diagram the model
    // got wrong is silently DROPPED -- no "Syntax error" box, no orphan graphics.
    // A data-driven page can't guarantee valid Mermaid; a missing diagram beats
    // an error box.
    if (!window.mermaid) return;
    var blocks = document.querySelectorAll('pre.mermaid');
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i], src = el.textContent;
      try {
        if ((await mermaid.parse(src, { suppressErrors: true })) === false) { el.remove(); continue; }
        var out = await mermaid.render('mmd' + i, src);
        el.innerHTML = out.svg;
      } catch (e) {
        console.warn('crawl: diagram ' + i + ' failed to render', e);
        el.remove();
      }
    }
  });
</script>"""

TOKENS = """  :root {
    --bg: #f7f8fa; --surface: #fff; --text: #101828; --muted: #667085;
    --faint: #98a2b3; --rule: #e4e7ec; --line: #eef0f3;
    --accent: #2563eb; --accent-soft: #dbeafe; --good: #16a34a; --stone: #9aa4b2;
    --stone-bg: #f2f4f7; --shadow: 0 1px 2px rgba(16,24,40,.05); --radius: 12px;
    --body-text: #344054; --body-soft: #475467;
    --font: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    --mono: 'JetBrains Mono', ui-monospace, Consolas, monospace;
    --code-bg: #0f172a; --code-fg: #e2e8f0; --thumb: #cbd2dc;
  }
  * { box-sizing: border-box; }
  code, .mono { font-family: var(--mono); }
  pre { background: var(--code-bg); color: var(--code-fg); border-radius: 8px; overflow-x: auto; }
  /* let highlight.js color the tokens, but keep our own dark pre background */
  pre code.hljs { background: transparent; padding: 0; color: var(--code-fg); }
  code { font-family: var(--mono); background: var(--stone-bg); color: var(--text); border-radius: 4px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid var(--rule); text-align: left; vertical-align: top; }
  th { background: var(--stone-bg); color: var(--muted); }
"""

# Included after each renderer's own rules, so a per-analysis accent or a
# layout rule set in between cannot outrank the dark surface it sits on.
DARK_TOKENS = """  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b0f19; --surface: #141a27; --text: #e6e9ef; --muted: #98a2b3;
      --faint: #6c7689; --rule: #232b3a; --line: #1b2230;
      --stone-bg: #1b2230; --shadow: 0 1px 2px rgba(0,0,0,.4);
      --body-text: #c3c9d5; --body-soft: #a6aebd; --thumb: #2a3346;
      /* A step lighter than the page, so a code block still reads as raised. */
      --code-bg: #161d2c;
      --accent-soft: #1d2a44;
    }
    /* Derived where the browser can, so the tint follows whichever renderer set
       --accent. The @supports guard is what preserves the flat value above: a
       custom property holding an unsupported color-mix is accepted at parse
       time and only fails in the property that USES it, where MDN says "the
       initial or inherited value of the property is used" -- the earlier flat
       declaration does not come back. color-mix has been Baseline "widely
       available" since May 2023. */
    @supports (color: color-mix(in srgb, red 50%, blue)) {
      :root { --accent-soft: color-mix(in srgb, var(--accent) 22%, var(--surface)); }
    }
    .card-top { background: var(--surface); }
  }"""
