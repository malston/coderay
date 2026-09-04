"""Reverse engineer the product story from the source (ch05)."""
import os
import sys

from pocketflow import Flow

from crawl.core.runner import run_analysis
from .nodes import FetchRepo, PainScene, VariantSentence, CompetitivePositioning, SurprisesAndAbsences
# This analysis hand-builds its page from structured data, so it keeps its own
# renderer; crawl.core.render defers to these.
from .render import render_html, render_markdown  # noqa: F401

NAME = "product-intent"

ENV_DEFAULTS = {}

def add_arguments(parser):
    parser.add_argument("--include", action="append", default=[],
                        help=".gitignore-style pattern: keep only matching "
                             "paths. Repeatable.")
    parser.add_argument("--exclude", action="append", default=[],
                        help=".gitignore-style pattern: drop matching paths. "
                             "Repeatable.")

def init_shared(args):
    return {
        "repo_path": args.repo_path,
        "include": list(getattr(args, "include", []) or []),
        "exclude": list(getattr(args, "exclude", []) or []),
    }

def build_flow():
    fetch, pain, variant = FetchRepo(), PainScene(), VariantSentence()
    positioning, surprises = CompetitivePositioning(), SurprisesAndAbsences()
    fetch >> pain >> variant >> positioning >> surprises
    return Flow(start=fetch)


def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
