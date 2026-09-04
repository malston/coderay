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
from crawl.core.runner import write_report

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"


def regenerate(analysis_name, out_dir):
    """Render the analysis's fixture input through the runner's own write path."""
    shared = json.loads((GOLDEN / analysis_name / "shared.json").read_text(encoding="utf-8"))
    write_report(ANALYSES[analysis_name], "toy_repo", shared, out_dir)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis", help="the analysis to regenerate, e.g. backend")
    args = ap.parse_args()
    if args.analysis not in ANALYSES:
        sys.exit(f"{args.analysis!r} is not a registered analysis; one of {sorted(ANALYSES)}")
    out_dir = GOLDEN / args.analysis
    if not (out_dir / "shared.json").is_file():
        sys.exit(f"no fixture input at {out_dir / 'shared.json'}")
    regenerate(args.analysis, out_dir)
    print(f"wrote {out_dir}/index.html and {out_dir}/index.md")


if __name__ == "__main__":
    main()
