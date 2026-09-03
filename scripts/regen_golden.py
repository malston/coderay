#!/usr/bin/env python3
"""Regenerate a golden render fixture from the sibling port source.

The golden files under tests/fixtures/golden/<analysis>/ pin the exact HTML and
markdown a ported analysis produces for a fixed `shared` dict. They are
generated from the port source of record, not from crack itself, so the test
proves the port stayed faithful rather than proving crack agrees with itself.

Use it when a deliberate change to the card engine or to an analysis's THEME or
SECTIONS makes a golden test fail. Never use it to silence an unexplained
failure -- diff the output first and know why it moved.

    scripts/regen_golden.py backend
    scripts/regen_golden.py backend --sibling ~/code/Crack-Any-Codebase-with-AI

The sibling checkout must be on the pinned port-source commit; the script
refuses to run otherwise. See docs/superpowers/specs/2026-09-01-analysis-port-design.md.

Run this with the sibling checkout's own Python, not `uv run` -- that activates
this project's venv, where coderay's own `crack` package is installed, and an
import of `crack` would silently resolve there instead of the sibling.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

PORT_SOURCE_COMMIT = "34f0ad2a7044284555911590ca3773c92e1244ac"
DEFAULT_SIBLING = pathlib.Path.home() / "code" / "Crack-Any-Codebase-with-AI"
GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"


# Places where crack deliberately differs from the port source. Every entry is
# applied to the generated HTML, so the fixture keeps deriving from the pinned
# upstream commit rather than from crack's own renderer, which would make the
# golden test check crack against itself. Each entry must still match, so a
# divergence that upstream later adopts fails loudly here instead of rotting.
#
# Keyed by analysis, because the bespoke renderers are not the card engine and
# do not carry its exact strings: git_history's mermaid line has no `flowchart`
# option, so the card entry cannot match it and a single shared list would
# make the script exit on every analysis but one.
CARD_DIVERGENCES = [
    # coderay-q2r.11: mermaid reads diagram source back out of textContent with
    # the HTML escaping already decoded, so 'loose', which does not sanitise,
    # leaves LLM-authored labels executable. tour has always used 'strict'.
    ("  if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: 'neutral', "
     "securityLevel: 'loose', flowchart: { htmlLabels: true } });",
     "  // 'strict' sanitises LLM-authored diagram labels; see coderay-q2r.11.\n"
     "  if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: 'neutral', "
     "securityLevel: 'strict' });"),

    # coderay-q2r.19: the port source loads all three from jsdelivr bare, and
    # mermaid from a floating major range. tour, which is coderay's own, has
    # always pinned an exact version with an integrity hash; this brings the
    # card engine up to it. Google Fonts is left alone on purpose: its css2
    # endpoint varies its @font-face sources by user-agent, so one hash would
    # block the stylesheet for some browsers.
    ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/'
     'cdn-release@11.9.0/build/styles/github-dark.min.css">',
     '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/'
     'cdn-release@11.9.0/build/styles/github-dark.min.css"\n'
     '  integrity="sha384-wH75j6z1lH97ZOpMOInqhgKzFkAInZPPSPlZpYKYTOqsaizPvhQZmAtLcPKXpLyH" '
     'crossorigin="anonymous">'),
    ('<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/'
     'build/highlight.min.js"></script>',
     '<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/'
     'build/highlight.min.js"\n'
     '  integrity="sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp" '
     'crossorigin="anonymous"></script>'),
    ('<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>',
     '<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"\n'
     '  integrity="sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2" '
     'crossorigin="anonymous"></script>'),
]


# The bespoke renderers ship their own copy of the CDN loading and mermaid
# config, so the same two fixes have to be re-applied there (coderay-q2r.11 for
# securityLevel, coderay-q2r.19 for pinning and SRI).
_SRI = [
    ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/'
     'cdn-release@11.9.0/build/styles/github-dark.min.css">',
     '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/'
     'cdn-release@11.9.0/build/styles/github-dark.min.css"\n'
     '  integrity="sha384-wH75j6z1lH97ZOpMOInqhgKzFkAInZPPSPlZpYKYTOqsaizPvhQZmAtLcPKXpLyH" '
     'crossorigin="anonymous">'),
    ('<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/'
     'build/highlight.min.js"></script>',
     '<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/'
     'build/highlight.min.js"\n'
     '  integrity="sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp" '
     'crossorigin="anonymous"></script>'),
    ('<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>',
     '<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"\n'
     '  integrity="sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2" '
     'crossorigin="anonymous"></script>'),
]

BESPOKE_DIVERGENCES = _SRI + [
    ("  if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: 'neutral', "
     "securityLevel: 'loose' });",
     "  // 'strict' sanitises LLM-authored diagram labels; see coderay-q2r.11.\n"
     "  if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: 'neutral', "
     "securityLevel: 'strict' });"),
]

# Analyses whose page is built by their own render_html rather than the card
# engine. crack.core.render defers to them, so regen reaches them unchanged;
# only the divergence set differs.
BESPOKE = {"git-history", "product-intent"}


def divergences_for(analysis_name):
    return BESPOKE_DIVERGENCES if analysis_name in BESPOKE else CARD_DIVERGENCES


def _apply_divergences(html, divergences):
    for old, new in divergences:
        if old not in html:
            sys.exit(f"divergence no longer applies, upstream may have adopted it: {old!r}")
        html = html.replace(old, new)
    return html


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis", help="the analysis to regenerate, e.g. backend")
    ap.add_argument("--sibling", type=pathlib.Path, default=DEFAULT_SIBLING,
                    help=f"port source checkout (default: {DEFAULT_SIBLING})")
    ap.add_argument("--allow-any-commit", action="store_true",
                    help="skip the pinned-commit check (you must say why in the commit message)")
    args = ap.parse_args()

    out_dir = GOLDEN / args.analysis
    shared_path = out_dir / "shared.json"
    if not shared_path.is_file():
        sys.exit(f"no fixture input at {shared_path}")

    head = subprocess.run(["git", "-C", str(args.sibling), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != PORT_SOURCE_COMMIT and not args.allow_any_commit:
        sys.exit(f"{args.sibling} is at {head or '(not a git checkout)'}, "
                 f"expected the pinned port source {PORT_SOURCE_COMMIT}.\n"
                 f"Check it out, or pass --allow-any-commit deliberately.")

    sys.path.insert(0, str(args.sibling / "src"))
    import crack as _crack

    resolved = os.path.realpath(_crack.__file__)
    sibling_root = os.path.realpath(str(args.sibling))
    if not resolved.startswith(sibling_root + os.sep):
        sys.exit(f"imported crack from {resolved}, not under {sibling_root}.\n"
                 f"This means the sibling's crack package was shadowed by another "
                 f"installed crack (likely this project's own venv). Refusing to "
                 f"write golden files generated by the wrong package. Run this "
                 f"script with a plain python interpreter, not `uv run`.")
    print(f"using crack from {resolved}")

    from crack.analyses import load           # the sibling's registry, not ours
    from crack.core import render

    analysis = load(args.analysis)
    shared = json.loads(shared_path.read_text(encoding="utf-8"))
    html = _apply_divergences(render.render_html(analysis, "toy_repo", shared),
                              divergences_for(args.analysis))
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "index.md").write_text(render.render_markdown(analysis, "toy_repo", shared), encoding="utf-8")
    print(f"wrote {out_dir}/index.html and {out_dir}/index.md from {args.sibling} @ {head[:7]}")

if __name__ == "__main__":
    main()
