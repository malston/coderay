#!/usr/bin/env python3
"""Regenerate the tour's golden render fixture.

The card-family fixtures come from scripts/regen_golden.py, which goes through
crawl.core.runner.write_report. The tour does not use that path -- it writes
index.md, index.html and a pair of files per chapter straight out of run() --
so it needs its own regeneration entry point and its own fixture directory.

The fixture lives in tests/fixtures/golden_tour/ rather than beside the others
in tests/fixtures/golden/, because tests there enumerate that directory and
render each name through the card engine, which the tour has no THEME for.

Use it when a deliberate change to the tour's renderer makes tests/test_tour_golden.py
fail. Never use it to silence an unexplained failure -- diff the output first
and know why it moved.

    uv run scripts/regen_tour_golden.py
"""
import json
import pathlib
import sys

from crawl.analyses.tour.render import (
    write_chapter_files,
    write_index_html,
    write_index_md,
)

FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_tour"


def render_into(out_dir):
    """Write the whole tour output for the committed input into out_dir."""
    args = json.loads((FIXTURE / "input.json").read_text(encoding="utf-8"))
    out = str(out_dir)
    write_index_md(args["chapters"], args["repo_name"], args["lens"], args["summary"],
                   args["mermaid"], out, generated_at=args["generated_at"])
    write_index_html(args["chapters"], args["repo_name"], args["lens"], args["summary"],
                     args["mermaid"], args["selected_files"], args["selection_reasoning"],
                     out, generated_at=args["generated_at"])
    write_chapter_files(args["chapters"], args["repo_name"], out, args["relationships"],
                        generated_at=args["generated_at"])


def main():
    if not (FIXTURE / "input.json").is_file():
        sys.exit(f"no fixture input at {FIXTURE / 'input.json'}")
    render_into(FIXTURE)
    written = sorted(p.name for p in FIXTURE.iterdir() if p.name != "input.json")
    print(f"wrote {len(written)} files into {FIXTURE}: {', '.join(written)}")


if __name__ == "__main__":
    main()
