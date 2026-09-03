"""Read the product roadmap already written in the git log (ch06)."""

import os
import sys

from pocketflow import Flow

from crack.core import OverviewNode
from crack.core.runner import repo_name_of, run_analysis
from .nodes import FetchHistory, NameEras, ProfileEras, Graveyard
# This analysis builds its page from structured data rather than markdown
# blobs, so it keeps its own renderer; crack.core.render defers to these.
from .render import render_html, render_markdown  # noqa: F401

NAME = "git-history"

ENV_DEFAULTS = {}

def add_arguments(parser):
    parser.add_argument("--max-graves", type=int, default=6,
                        help="how many killed features to dig up (default 6)")
    parser.add_argument("--grave-min-files", type=int, default=8,
                        help="a deletion counts as a killed feature at this "
                             "many files (default 8)")

def init_shared(args):
    return {
        "repo_path": args.repo_path,
        "max_graves": getattr(args, "max_graves", 6),
        "grave_min_files": getattr(args, "grave_min_files", 8),
    }

def build_flow():
    fetch, eras = FetchHistory(), NameEras()
    profile, graves = ProfileEras(), Graveyard()
    overview = OverviewNode(overview_spec)
    fetch >> eras >> profile >> graves >> overview
    return Flow(start=fetch)


# The friendly "start here" welcome runs on the shared OverviewNode
# (crack/core/nodes.py); this just supplies the chapter-specific bits it needs.
def overview_spec(shared):
    name = repo_name_of(shared["repo_path"]) or shared["repo_path"]
    eras = shared.get("eras", [])
    return {
        "name": name,
        "what": "a product's story told through its git history",
        "sections": [
            ("The eras", "the product's life split into named chapters, oldest first"),
            ("Cast & mood", "who drove each era and what the day-to-day work was"),
            ("The graveyard", "the features the team built and later deleted"),
        ],
        "facts": (f"{len(eras)} eras: " + ", ".join(e["name"] for e in eras) + ". "
                  + f"{len(shared.get('graves', []))} killed features in the graveyard. "
                  + f"{len(shared.get('commits', [])):,} commits total."),
    }


def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
