"""Read the product roadmap already written in the git log."""

import os
import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.runner import repo_name_of, require_directory, run_analysis
from crawl.core.preview import Preview
from .nodes import (BULK_ADD_FLOOR, BULK_DEL_FLOOR, SHALLOW_WARNING,
                    FetchHistory, NameEras, ProfileEras, Graveyard)
from .gitlog import repo_root
# This analysis builds its page from structured data rather than markdown
# blobs, so it keeps its own renderer; crawl.core.render defers to these.
from .render import render_html, render_markdown  # noqa: F401

NAME = "git-history"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"commits", "commits_asc", "bulk_adds", "bulk_dels"})

ENV_DEFAULTS = {}

def add_arguments(parser):
    parser.add_argument("--max-graves", type=int, default=6,
                        help="how many killed features to dig up (default 6)")
    parser.add_argument("--grave-min-files", type=int, default=8,
                        help="a deletion counts as a killed feature at this "
                             "many files (default 8)")
    parser.add_argument("--profile-max-commits", type=int, default=400,
                        help="cap on commits sampled into one era's profile "
                             "prompt (default 400)")
    parser.add_argument("--profile-diff-chars", type=int, default=2500,
                        help="cap on characters per landmark diff in a "
                             "profile prompt (default 2500)")

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call. There are no file counts
    here: this analysis reads commits. The eras are the model's answer, so a
    preview cannot report them.

    repo_root first, as run() does: `git -C` walks up to the enclosing .git, so a
    subdirectory would otherwise be previewed as its parent, under the wrong name
    and with the parent's whole history (coderay-q2r.38).

    The four flags size the prompts and filter the graveyard after the crawl;
    FetchHistory carries its own thresholds, so none of them moves these counts.

    exec() is the whole crawl -- post() only prints and updates shared."""
    repo_root(args.repo_path)
    log = FetchHistory().exec(args.repo_path)
    counts = {"commits": len(log["commits"]),
              f"bulk additions ({BULK_ADD_FLOOR}+ files)": len(log["bulk_adds"]),
              f"bulk deletions ({BULK_DEL_FLOOR}+ files)": len(log["bulk_dels"])}
    notes = [SHALLOW_WARNING] if log["shallow"] else []  # coderay-q2r.38
    return {"counts": counts, "files": {}, "notes": notes}


def sent(shared):
    """What left the machine: no files here. The whole log is summarised for the
    era names, with the biggest bulk changes' subject lines verbatim; each era's
    sampled commits' subject lines and the landmark and grave diffs go out
    whole (coderay-3eu)."""
    listed, diffs = set(shared.get("survey_commits_sent", [])), set()
    for p in shared.get("profiles", []):
        listed.update(p.get("commits_sent", []))
        diffs.update(p.get("diffs_sent", []))
    diffs.update(g["commit"]["hash"] for g in shared.get("graves", []))
    return {"commits_logged": len(shared.get("commits", [])),
            "commits_listed": sorted(listed), "diffs": sorted(diffs)}


def init_shared(args):
    return {
        "repo_path": args.repo_path,
        "max_graves": getattr(args, "max_graves", 6),
        "grave_min_files": getattr(args, "grave_min_files", 8),
        "profile_max_commits": getattr(args, "profile_max_commits", 400),
        "profile_diff_chars": getattr(args, "profile_diff_chars", 2500),
    }

def build_flow():
    fetch, eras = FetchHistory(), NameEras()
    profile, graves = ProfileEras(), Graveyard()
    overview = OverviewNode(overview_spec)
    fetch >> eras >> profile >> graves >> overview
    return Flow(start=fetch)


# The friendly "start here" welcome runs on the shared OverviewNode
# (crawl/core/nodes.py); this just supplies the analysis-specific bits it needs.
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
    require_directory(args.repo_path)
    repo_root(args.repo_path)  # coderay-q2r.38
    run_analysis(sys.modules[__name__], args)
