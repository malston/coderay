#!/usr/bin/env python3
"""Regenerate a golden render fixture from this package's own renderer.

The golden files under tests/fixtures/golden/<analysis>/ pin the exact HTML and
markdown an analysis produces for a fixed `shared` dict, so tests/test_golden.py
catches any drift in the card engine, a THEME value, or a section definition.

Use it when a deliberate change to the renderer makes a golden test fail.
Never use it to silence an unexplained failure -- diff the output first and
know why it moved.

    uv run scripts/regen_golden.py backend
"""
import argparse
import json
import pathlib
import sys

from crawl.analyses import ANALYSES
from crawl.core import render

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"


def regenerate(analysis_name, out_dir):
    """Render the analysis's fixture input and write index.html and index.md into out_dir."""
    shared_path = GOLDEN / analysis_name / "shared.json"
    if not shared_path.is_file():
        sys.exit(f"no fixture input at {shared_path}")
    analysis = ANALYSES[analysis_name]
    shared = json.loads(shared_path.read_text(encoding="utf-8"))
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render.render_html(analysis, "toy_repo", shared), encoding="utf-8")
    (out_dir / "index.md").write_text(render.render_markdown(analysis, "toy_repo", shared), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis", help="the analysis to regenerate, e.g. backend")
    args = ap.parse_args()
    out_dir = GOLDEN / args.analysis
    regenerate(args.analysis, out_dir)
    print(f"wrote {out_dir}/index.html and {out_dir}/index.md")


if __name__ == "__main__":
    main()
