"""The visual layer every page template includes.

The analyses own different page shapes on purpose -- the card family renders
one page of horizontal rails from SECTIONS and THEME, the tour writes a
multi-file reading tour, and two analyses hand-build their pages from
structured data -- but they are the same product, so the fonts, the palette,
the code typography and the third-party head tags are defined here once and
included by all four. Layout and type sizes stay with each renderer.

Five templates across those four renderers each carry a {head_assets},
{tokens} and {dark_tokens} slot, in that order, with {dark_tokens} closing the
<style> block. These arrive as .format() values rather than as part of a format
string, so .format() never rescans them and their braces are not doubled.

TOKENS carries default colours; a renderer that wants its own writes a :root
override after it. Anything derived with color-mix is declared flat first and
mixed inside an @supports block, never as a bare second declaration.
"""

#: How far --accent-ink pulls the accent toward the text colour. Matches the
#: color-mix percentage in TOKENS, so the flat and derived values agree.
INK_MIX = 0.60
#: The light scheme's --text. flat_ink mixes toward it, because the flat value
#: only ever renders on a browser that has no color-mix and no dark block.
_LIGHT_TEXT = (0x10, 0x18, 0x28)


def flat_ink(accent):
    """The fallback --accent-ink for an accent, for browsers without color-mix.

    color-mix in srgb interpolates each channel, so this is the same arithmetic
    the stylesheet does, kept here rather than written out per analysis.
    """
    hexed = accent.lstrip("#")
    if len(hexed) == 3:  # CSS shorthand: #abc means #aabbcc
        hexed = "".join(c * 2 for c in hexed)
    channels = (int(hexed[i:i + 2], 16) for i in (0, 2, 4))
    mixed = (round(c * INK_MIX + t * (1 - INK_MIX))
             for c, t in zip(channels, _LIGHT_TEXT))
    return "#%02x%02x%02x" % tuple(mixed)


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
    // Render each diagram, but validate first with parse(): a data-driven page
    // can't guarantee valid Mermaid, and mermaid's own "Syntax error" box is
    // not what a reader should be handed. One that fails becomes a placeholder
    // rather than disappearing (coderay-2l9): the headings and captions around
    // it are written by the template and stay either way, so removing the block
    // left a caption for artwork that was not there, and left the reader unable
    // to tell an incomplete report from a complete one.
    function markFailed(el) {
      // Drops the mermaid class too, so nothing tries to render the notice.
      el.className = 'diagram-failed';
      el.textContent = 'This diagram could not be rendered.';
    }
    if (!window.mermaid) return;
    var blocks = document.querySelectorAll('pre.mermaid');
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i], src = el.textContent;
      try {
        if ((await mermaid.parse(src, { suppressErrors: true })) === false) {
          console.warn('crawl: diagram ' + i + ' is not valid mermaid');
          markFailed(el);
          continue;
        }
        var out = await mermaid.render('mmd' + i, src);
        el.innerHTML = out.svg;
      } catch (e) {
        console.warn('crawl: diagram ' + i + ' failed to render', e);
        markFailed(el);
      }
    }
  });
</script>"""

TOKENS = """  :root {
    --bg: #f7f8fa; --surface: #fff; --text: #101828; --muted: #667085;
    --faint: #98a2b3; --rule: #e4e7ec; --line: #eef0f3;
    --accent: #2563eb; --accent-soft: #dbeafe; --accent-ink: #1d459d;
    --good: #16a34a; --stone: #9aa4b2;
    --stone-bg: #f2f4f7; --shadow: 0 1px 2px rgba(16,24,40,.05); --radius: 12px;
    --body-text: #344054; --body-soft: #475467;
    --font: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    --mono: 'JetBrains Mono', ui-monospace, Consolas, monospace;
    --code-bg: #0f172a; --code-fg: #e2e8f0; --thumb: #cbd2dc;
    /* The top edge of a card, tinted in light and flat in dark. */
    --card-top: #fbfcfe;
  }
  * { box-sizing: border-box; }
  code, .mono { font-family: var(--mono); }
  pre { background: var(--code-bg); color: var(--code-fg); border-radius: 8px; overflow-x: auto; }
  /* Until highlight.js runs, a code block carries no .hljs class and falls
     to the `code` rule below, whose chip background lands on top of the
     dark pre. A blocked CDN or a failed hash leaves it that way. */
  pre code { background: transparent; color: inherit; }
  /* let highlight.js color the tokens, but keep our own dark pre background */
  pre code.hljs { background: transparent; padding: 0; color: var(--code-fg); }
  code { background: var(--stone-bg); color: var(--text); border-radius: 4px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid var(--rule); text-align: left; vertical-align: top; }
  th { background: var(--stone-bg); color: var(--muted); }
  /* A diagram block holds its own source until mermaid replaces it with an
     SVG. If mermaid never loads -- a blocked CDN, a failed hash, no network --
     it is never replaced, and the source is what the reader gets. Without this
     the block keeps --code-fg from the `pre` rule above, which is near-white
     and meant for the dark code background, so on a light surface the source
     lands at 1.23:1 and the reader sees an empty box. `inherit` is not the
     answer: a diagram inside a hero band would inherit white. The background
     has to come off in the same rule: page ink on --code-bg is 1.01:1, the
     same defect turned around. transparent takes whichever token surface the
     block sits on, which is right in both schemes. */
  pre.mermaid { background: transparent; color: var(--text); }
  /* Stands in for a diagram the model got wrong (coderay-2l9). Quiet enough
     not to read as an error in a report someone forwards, present enough that
     the reader knows something is missing rather than absent. */
  .diagram-failed { background: var(--surface); color: var(--faint);
    border: 1px dashed var(--rule); border-radius: 8px; padding: 16px;
    text-align: center; font-size: .8rem; font-style: italic; margin: 0; }

  /* --accent is the brand hue, picked to look right as a bar, a border or a
     fill. Reading it as small text is a different question: every analysis
     accent lands under WCAG AA against one scheme's surfaces or the other's
     (schema is 2.63:1 on the dark surface, architecture 3.00:1 on the light
     one). --accent-ink carries the same hue pulled toward whichever text
     colour is in force, which clears AA in both. Use it wherever the accent
     is the ink; the flat value above is the default accent's, and a renderer
     that sets its own --accent sets its own flat ink beside it. */
  @supports (color: color-mix(in srgb, red 50%, blue)) {
    :root { --accent-ink: color-mix(in srgb, var(--accent) 60%, var(--text)); }
  }
"""

# Included after each renderer's own rules, so an --accent-soft or a layout
# rule set in between cannot outrank the dark surface it sits on.
DARK_TOKENS = """  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b0f19; --surface: #141a27; --text: #e6e9ef; --muted: #98a2b3;
      /* #6c7689 reads as 3.80:1 on --surface, under AA for the small text
         that carries it. */
      --faint: #7d8798; --rule: #232b3a; --line: #1b2230;
      --stone-bg: #1b2230; --shadow: 0 1px 2px rgba(0,0,0,.4);
      --shadow-lg: 0 8px 26px rgba(0,0,0,.55);
      --body-text: #c3c9d5; --body-soft: #a6aebd; --thumb: #2a3346;
      /* A step lighter than the page, so a code block still reads as raised. */
      --code-bg: #161d2c;
      --accent-soft: #1d2a44; --card-top: var(--surface);
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
  }"""
