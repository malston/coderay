"""Read the product roadmap already written in the git log."""

import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.runner import repo_name_of, require_directory, run_analysis
from crawl.core.preview import Preview, aborts
from crawl.core.estimate import Prompt, shell_chars
from .nodes import (BULK_ADD_FLOOR, BULK_DEL_FLOOR, GRAVE_MIN_FILES, MAX_GRAVES,
                    NO_COMMITS, PROFILE_DIFF_CHARS, PROFILE_MAX_COMMITS,
                    SHALLOW_WARNING, FetchHistory, NameEras, ProfileEras, Graveyard)
from .gitlog import repo_root
# This analysis builds its page from structured data rather than markdown
# blobs, so it keeps its own renderer; crawl.core.render defers to these.
from .render import render_html, render_markdown  # noqa: F401

NAME = "git-history"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"commits", "commits_asc", "bulk_adds", "bulk_dels"})

ENV_DEFAULTS = {}

def add_arguments(parser):
    # The defaults are the constants in nodes.py, so the number a run sends and
    # the number an estimate prices cannot drift apart.
    parser.add_argument("--max-graves", type=int, default=MAX_GRAVES,
                        help=f"how many killed features to dig up (default {MAX_GRAVES})")
    parser.add_argument("--grave-min-files", type=int, default=GRAVE_MIN_FILES,
                        help="a deletion counts as a killed feature at this "
                             f"many files (default {GRAVE_MIN_FILES})")
    parser.add_argument("--profile-max-commits", type=int, default=PROFILE_MAX_COMMITS,
                        help="cap on commits sampled into one era's profile "
                             f"prompt (default {PROFILE_MAX_COMMITS})")
    parser.add_argument("--profile-diff-chars", type=int, default=PROFILE_DIFF_CHARS,
                        help="cap on characters per landmark diff in a "
                             f"profile prompt (default {PROFILE_DIFF_CHARS})")

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call. There are no file counts
    here: this analysis reads commits. It carries none of the three canonical
    quantities. An empty included/dropped set would claim it looked at files and
    found none, and there is no assembled length either: exec() returns a commit
    record, and the prompt text is built downstream in NameEras.prep and
    ProfileEras.prep, with the diffs fetched later still (coderay-05w.6). The
    eras are the model's answer, so a preview cannot report them.

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
    if not log["commits"]:
        notes.append(aborts(NO_COMMITS))
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
        "max_graves": getattr(args, "max_graves", MAX_GRAVES),
        "grave_min_files": getattr(args, "grave_min_files", GRAVE_MIN_FILES),
        "profile_max_commits": getattr(args, "profile_max_commits", PROFILE_MAX_COMMITS),
        "profile_diff_chars": getattr(args, "profile_diff_chars", PROFILE_DIFF_CHARS),
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



def prompt_plan(args, preview):
    """Four prompts. This analysis reports no assembled_chars: its crawl returns
    a commit record and the prompt text is built downstream. So the bodies are
    sized from the caps the nodes themselves pass to show_diff, and the survey
    prompt by calling NameEras.prep, the way tour's preview reuses SmartCrawl's.

    That second call re-reads the log preview() just read, because the record has
    no place on a Preview to travel in. Fixing it needs a contract decision;
    coderay-5fp holds the options."""
    from crawl.core.estimate import overview_prompt
    from . import gitlog as gl
    from .nodes import ERA_RANGE, GRAVE_DIFF_CHARS, PROMPTS_DIR, FetchHistory, NameEras
    # The flags this command accepts, not the defaults behind them: a run
    # configured with --profile-diff-chars 50000 sends twenty times the text.
    max_commits = getattr(args, "profile_max_commits", PROFILE_MAX_COMMITS)
    diff_chars = getattr(args, "profile_diff_chars", PROFILE_DIFF_CHARS)
    max_graves = getattr(args, "max_graves", MAX_GRAVES)
    log = FetchHistory().exec(args.repo_path)
    survey_slots = ("heatmap_summary", "pivots_summary",
                    "additions_summary", "deletions_summary")
    survey_shell = shell_chars(PROMPTS_DIR, "name-eras.md", survey_slots)
    survey_prompt, _listed = NameEras().prep(dict(log, repo_path=args.repo_path))

    era_slots = ("commit_stream", "prior_summaries", "era_index", "total_eras",
                 "era_name", "era_start", "era_end", "era_description") + tuple(
        f"{w}_{f}" for w in ("opening", "early", "mid", "late", "closing")
        for f in ("hash", "date", "subject", "diff"))
    sampled, _ = gl.sample_commits(log["commits_asc"], max_commits)
    era_body = len(gl.commit_stream(sampled)) + 5 * diff_chars

    grave_slots = ("diff", "hash", "subject", "author", "date",
                   "era_name", "era_start", "era_end", "era_description")
    return [
        Prompt("name-eras.md", survey_shell, len(survey_prompt) - survey_shell, (1, 1)),
        Prompt("profile-era.md", shell_chars(PROMPTS_DIR, "profile-era.md", era_slots),
               era_body, ERA_RANGE,
               note=f"one call per era; name-eras.md asks for {ERA_RANGE[0]} to "
                    f"{ERA_RANGE[1]}. Each carries a commit stream sampled to "
                    f"{max_commits} plus 5 diffs capped at {diff_chars:,}. The "
                    "stream here sizes one era holding the whole history, so it "
                    "is an upper bound"),
        Prompt("graveyard-entry.md",
               shell_chars(PROMPTS_DIR, "graveyard-entry.md", grave_slots),
               GRAVE_DIFF_CHARS, (0, max_graves),
               note=f"one call per grave, at most {max_graves}; a repo with no bulk "
                    "deletions buys none"),
        overview_prompt(),
    ]


def run(args) -> None:
    require_directory(args.repo_path)
    repo_root(args.repo_path)  # coderay-q2r.38
    run_analysis(sys.modules[__name__], args)
