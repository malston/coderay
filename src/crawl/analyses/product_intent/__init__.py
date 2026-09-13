"""Reverse engineer the product story from the source."""
import sys

from pocketflow import Flow

from crawl.core.runner import require_directory, run_analysis
from crawl.core.text import codebase_budget_argument
from crawl.core.preview import Preview, aborts
from crawl.core.estimate import Prompt, shell_chars
from .nodes import (DEFAULT_MAX_CHARS, FetchRepo, PainScene, VariantSentence,
                    CompetitivePositioning, SurprisesAndAbsences, bundle,
                    no_source_reason)
# This analysis hand-builds its page from structured data, so it keeps its own
# renderer; crawl.core.render defers to these.
from .render import render_html, render_markdown  # noqa: F401

NAME = "product-intent"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"codebase"})

ENV_DEFAULTS = {}

def add_arguments(parser):
    parser.add_argument("--include", action="append", default=[],
                        help=".gitignore-style pattern: keep only matching "
                             "paths. Repeatable.")
    parser.add_argument("--exclude", action="append", default=[],
                        help=".gitignore-style pattern: drop matching paths. "
                             "Repeatable.")
    parser.add_argument("--codebase-budget", **codebase_budget_argument(DEFAULT_MAX_CHARS))

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call. This is the one crawler
    that counts all three outright: what went in, what the budget dropped, and
    what would not decode. The dropped files are named as well as counted, which
    is what a recommendation about --include/--exclude has to be grounded in
    (coderay-05w.4). Unreadable files are counted but not named: they never
    became a repo-relative path."""
    include = list(getattr(args, "include", []) or [])
    exclude = list(getattr(args, "exclude", []) or [])
    codebase, stats = bundle(args.repo_path, include=include or None,
                             exclude=exclude or None, max_chars=args.codebase_budget)
    notes = []
    if not codebase.strip():
        notes.append(aborts(no_source_reason(args.repo_path, include, exclude)))
    return {"counts": {"files in the bundle": len(stats["files"]),
                       "dropped by the budget": len(stats["dropped_files"]),
                       "unreadable": stats["unreadable"]},
            "files": {"bundle": stats["files"], "dropped by the budget": stats["dropped_files"]},
            "included": stats["files"], "dropped": stats["dropped_files"],
            "assembled_chars": len(codebase), "notes": notes}


def sent(shared):
    """What left the machine: every source file the bundle carried whole (coderay-3eu)."""
    return {"files": shared.get("bundle_files", [])}


def init_shared(args):
    return {
        "repo_path": args.repo_path,
        "include": list(getattr(args, "include", []) or []),
        "exclude": list(getattr(args, "exclude", []) or []),
        "codebase_budget": args.codebase_budget,
    }

def build_flow():
    fetch, pain, variant = FetchRepo(), PainScene(), VariantSentence()
    positioning, surprises = CompetitivePositioning(), SurprisesAndAbsences()
    fetch >> pain >> variant >> positioning >> surprises
    return Flow(start=fetch)



def prompt_plan(args, preview):
    """Four prompts, each carrying the whole bundle once. No overview node here,
    and every count is fixed. None of these templates carries the house style
    slot; each writes its own instructions."""
    from .nodes import PROMPTS_DIR
    body = preview.get("assembled_chars") or 0
    return [Prompt(t, shell_chars(PROMPTS_DIR, t, ("codebase",)), body, (1, 1))
            for t in ("pain-scene.md", "variant-sentence.md",
                      "competitive-positioning.md", "surprises-and-absences.md")]


def run(args) -> None:
    require_directory(args.repo_path)
    run_analysis(sys.modules[__name__], args)
