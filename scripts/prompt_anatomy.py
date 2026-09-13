#!/usr/bin/env python3
"""Measure what every prompt in every analysis actually sends to the LLM.

Runs each analysis's crawl step against a target repo -- no LLM call, no
network -- then reports, per prompt template: the fixed cost of the template
itself, how many characters of repository text it carries, which slots only an
earlier LLM call can fill, and how many times it is sent in one run.

Use it to refresh the tables in docs/prompt-anatomy.md after editing a prompt
template, to size a new analysis's prompts, or to check what a budget change
does to the text a run sends. Use --dump to read one prompt end to end with its
slots filled, which is the fastest way to see what a template really looks like.

The SLOTS table below records where each slot's value comes from, which is not
derivable from the slot name. It is checked against the templates on every run:
a renamed, added, or removed slot fails with a message rather than quietly
reporting a wrong number.

    scripts/prompt_anatomy.py <repo_path> [analysis ...]
    scripts/prompt_anatomy.py <repo_path> schema --dump trace-flows
"""
import argparse
import importlib
import os
import sys
from pathlib import Path

from crawl.core import fill, house_style, read_prompt
from crawl.core.call_llm import CACHE_BREAKPOINT

ANALYSES = ["tour", "backend", "architecture", "interfaces", "schema",
            "git_history", "product_intent"]

# slot -> where its value comes from.
#   "crawl" : text this analysis's crawl step assembled; scales with the repo
#   "crawl-capped-N": the same, truncated to N chars by the node that sends it
#   "bundle": the LLM-picked codebase bundle (tour only); not knowable up front
#   "model" : output of an earlier LLM call in the same run
#   "small" : a number or short label
SLOTS = {
  "tour": {
    "select-files.md":          {"manifest": "crawl", "target_count": "small",
                                 "chars_per_file": "small"},
    "identify-abstractions.md": {"codebase": "bundle", "selected_files": "model"},
    "analyze-relationships.md": {"codebase": "bundle", "abstractions": "model"},
    "write-chapter.md":         {"codebase": "bundle", "instructions": "small",
                                 "name": "model", "description": "model",
                                 "chapter_num": "small", "total": "small",
                                 "prev_chapters": "model", "chapter_list": "model"},
  },
  "backend": {
    "pipeline.md":   {"codebase": "crawl"},
    "layer-code.md": {"codebase": "crawl"},
    "trace.md":      {"codebase": "crawl"},
  },
  "architecture": {
    "inventory.md":     {"codebase": "crawl"},
    "tech-stack.md":    {"codebase": "crawl", "inventory": "model"},
    "trace-request.md": {"codebase": "crawl", "inventory": "model"},
  },
  "interfaces": {
    "api-menu.md":          {"routes": "crawl"},
    "trace-action.md":      {"routes": "crawl", "groups": "model"},
    # handler_source is the files the model picked, read back off disk, or a
    # fallback file; routes is truncated to 60,000 chars in this one prompt.
    "endpoint-sequence.md": {"routes": "crawl-capped-60000",
                             "handler_source": "model", "flow": "model"},
  },
  "schema": {
    "schema-tour.md":     {"schema": "crawl"},
    "trace-flows.md":     {"schema": "crawl", "table_list": "model"},
    "table-deep-dive.md": {"schema": "crawl", "table_list": "model",
                           "product_name": "model", "one_liner": "model"},
    "migration-acts.md":  {"migration_names": "crawl"},
  },
  "git_history": {
    "name-eras.md":       {"heatmap_summary": "crawl", "pivots_summary": "crawl",
                           "additions_summary": "crawl", "deletions_summary": "crawl"},
    "profile-era.md":     {"commit_stream": "crawl", "prior_summaries": "model",
                           "era_index": "small", "total_eras": "small",
                           "era_name": "model", "era_start": "model",
                           "era_end": "model", "era_description": "model",
                           **{f"{w}_{f}": ("crawl" if f == "diff" else "small")
                              for w in ("opening", "early", "mid", "late", "closing")
                              for f in ("hash", "date", "subject", "diff")}},
    "graveyard-entry.md": {"diff": "crawl", "hash": "small", "subject": "small",
                           "author": "small", "date": "small",
                           "era_name": "model", "era_start": "model",
                           "era_end": "model", "era_description": "model"},
  },
  "product_intent": {
    "pain-scene.md":              {"codebase": "crawl"},
    "variant-sentence.md":        {"codebase": "crawl"},
    "competitive-positioning.md": {"codebase": "crawl"},
    "surprises-and-absences.md":  {"codebase": "crawl"},
  },
}

# How many times each prompt is sent in one complete run.
FIRES = {
  "tour": {"select-files.md": "1", "identify-abstractions.md": "1",
           "analyze-relationships.md": "1",
           "write-chapter.md": "once per chapter (model's answer)"},
  "backend": {"pipeline.md": "1", "layer-code.md": "1", "trace.md": "1"},
  "architecture": {"inventory.md": "1", "tech-stack.md": "1", "trace-request.md": "1"},
  "interfaces": {"api-menu.md": "1", "trace-action.md": "1",
                 "endpoint-sequence.md": "1 (plus 1 inline pick)"},
  "schema": {"schema-tour.md": "1", "trace-flows.md": "1",
             "table-deep-dive.md": "once per 4 tables (model's answer)",
             "migration-acts.md": "0 below MIGRATION_FLOOR, else 1"},
  "git_history": {"name-eras.md": "1",
                  "profile-era.md": "once per era (model's answer)",
                  "graveyard-entry.md": "once per grave, at most max_graves"},
  "product_intent": {"pain-scene.md": "1", "variant-sentence.md": "1",
                     "competitive-positioning.md": "1", "surprises-and-absences.md": "1"},
}

# Analyses ending with the shared OverviewNode (crawl/core/nodes.py).
HAS_OVERVIEW = {"backend", "architecture", "interfaces", "schema", "git_history"}


class CrawlArgs:
    """A namespace wide enough for any analysis's preview()."""
    def __init__(self, repo_path, budget):
        self.repo_path = repo_path
        self.codebase_budget = budget
        self.schema = None
        self.instructions = "beginner-tutorial"
        self.include = []
        self.exclude = []
        self.max_graves = 6


def prompts_dir(analysis):
    root = Path(importlib.import_module("crawl").__file__).parent
    return root / "analyses" / analysis / "prompts"


def check_slots(analysis):
    """Fail loudly when SLOTS has drifted from the templates on disk."""
    import re
    for name, known in SLOTS[analysis].items():
        path = prompts_dir(analysis) / name
        if not path.exists():
            sys.exit(f"{analysis}/{name}: in SLOTS but not on disk. Update {__file__}.")
        found = set(re.findall(r"\{([a-z_]+)\}", path.read_text(encoding="utf-8")))
        found.discard("house_style")   # filled by read_prompt, not by the node
        missing, extra = found - set(known), set(known) - found
        if missing or extra:
            sys.exit(f"{analysis}/{name}: SLOTS is stale. "
                     f"In the template but not in SLOTS: {sorted(missing) or 'none'}. "
                     f"In SLOTS but not in the template: {sorted(extra) or 'none'}. "
                     f"Update {__file__}.")
    on_disk = {p.name for p in prompts_dir(analysis).glob("*.md")}
    for name in sorted(on_disk - set(SLOTS[analysis])):
        sys.exit(f"{analysis}/{name}: on disk but not in SLOTS. Update {__file__}.")


def crawl_preview(analysis, args):
    mod = importlib.import_module(f"crawl.analyses.{analysis}")
    try:
        preview = mod.preview(args)
    except BaseException as e:          # SystemExit is how a crawl reports an abort
        return None, f"{type(e).__name__}: {e}"
    if analysis == "git_history":
        # Its prompts are sized from the commit record, which preview() does not
        # carry. Re-run the same crawl node the preview ran.
        from crawl.analyses.git_history.nodes import FetchHistory
        preview["_log"] = FetchHistory().exec(args.repo_path)
        preview["_repo_path"] = args.repo_path
    return preview, None


def crawled_chars(analysis, name, slots, preview, budget):
    """Characters of repository text this prompt carries, and a caveat if any."""
    n_crawl = sum(1 for k in slots.values() if k == "crawl")
    if any(k == "bundle" for k in slots.values()):
        return None, "bundle is LLM-picked; no preview can size it"
    caps = [int(k.rsplit("-", 1)[1]) for k in slots.values() if k.startswith("crawl-capped-")]
    if caps:
        ac = preview.get("assembled_chars") or 0
        carried = min(ac, caps[0]) + n_crawl * ac
        model_slots = [s for s, k in slots.items() if k == "model"]
        return carried, (f"crawled part only, truncated at {caps[0]:,}; "
                         f"{', '.join(model_slots)} unknowable before the run")
    if analysis == "schema" and name == "migration-acts.md":
        names = preview["files"].get("migrations", [])
        return sum(len(x) + 1 for x in names), None
    if analysis == "tour":
        return preview.get("assembled_chars", 0), "manifest, not the bundle"
    if analysis == "git_history":
        return _git_history_chars(name, preview)
    return (preview.get("assembled_chars") or 0) * n_crawl, None


def _git_history_chars(name, preview):
    """git-history reports no assembled_chars: its crawl step returns a commit
    record and the prompt text is built downstream, with diffs fetched later
    still. Size it the way the nodes do, from the same functions they call."""
    from crawl.analyses.git_history import gitlog as gl
    # Imported, not restated: a copy here would let docs/prompt-anatomy.md
    # report a cap the nodes no longer send.
    from crawl.analyses.git_history.nodes import (GRAVE_DIFF_CHARS, PROFILE_DIFF_CHARS,
                                                  PROFILE_MAX_COMMITS)
    log, repo = preview["_log"], preview["_repo_path"]
    if name == "name-eras.md":
        # Reuse the node's own prep rather than rebuilding its summary logic,
        # which drops pure renames before summarising. Subtract the shell to
        # leave the crawled part.
        from crawl.analyses.git_history.nodes import NameEras
        prompt, _listed = NameEras().prep(dict(log, repo_path=repo))
        shell = len(read_prompt(prompts_dir("git_history"), name)) - sum(
            len("{%s}" % s) for s in SLOTS["git_history"][name])
        return len(prompt) - shell, "heatmap, pivots, and bulk-change summaries"
    if name == "profile-era.md":
        asc = log["commits_asc"]
        if not asc:
            return 0, "no commits"
        # One era's worth, standing in for an era count only the model knows.
        # The whole history here is the upper bound on any single era.
        sampled, _ = gl.sample_commits(asc, PROFILE_MAX_COMMITS)
        stream = len(gl.commit_stream(sampled))
        return stream + 5 * PROFILE_DIFF_CHARS, (
            f"upper bound for one era: {len(sampled)} commits sampled from "
            f"{len(asc)} (cap {PROFILE_MAX_COMMITS}), plus 5 landmark diffs "
            f"capped at {PROFILE_DIFF_CHARS:,} each")
    if name == "graveyard-entry.md":
        return GRAVE_DIFF_CHARS, f"one diff with --stat, capped at {GRAVE_DIFF_CHARS:,}"
    return None, None


def report(analysis, args):
    check_slots(analysis)
    preview, err = crawl_preview(analysis, args)
    print("=" * 78)
    print(analysis)
    if err:
        print(f"  crawl step failed: {err}\n")
        return
    ac = preview.get("assembled_chars")
    print(f"  crawl assembled: {ac:,} chars" if ac is not None
          else "  crawl assembled: not reported by this analysis")
    for label, count in (preview.get("counts") or {}).items():
        print(f"    {label}: {count:,}")
    for note in preview.get("notes", []):
        print(f"  note: {note}")
    print()
    print(f"  {'template':<30}{'shell':>9}{'house':>7}{'crawled':>11}{'per call':>11}  fires")
    for name, slots in SLOTS[analysis].items():
        raw = read_prompt(prompts_dir(analysis), name)
        on_disk = (prompts_dir(analysis) / name).read_text(encoding="utf-8")
        shell = len(raw) - sum(len("{%s}" % s) for s in slots)
        body, caveat = crawled_chars(analysis, name, slots, preview, args.codebase_budget)
        has_hs = "yes" if "{house_style}" in on_disk else "no"
        per = f"{shell + body:,}" if body is not None else "see note"
        bp = "  [cache breakpoint]" if CACHE_BREAKPOINT in raw else ""
        print(f"  {name:<30}{shell:>9,}{has_hs:>7}"
              f"{(f'{body:,}' if body is not None else '?'):>11}{per:>11}"
              f"  {FIRES[analysis][name]}{bp}")
        if caveat:
            print(f"  {'':<30}{caveat}")
    if analysis in HAS_OVERVIEW:
        from crawl.core import overview as ov
        shell = len(ov._PROMPT) - sum(
            len("{%s}" % s) for s in
            ("name", "what", "facts", "sections", "headers", "house_style"))
        voice = len(house_style(with_evidence=False))
        print(f"  {'(shared OverviewNode)':<30}{shell + voice:>9,}{'voice':>7}"
              f"{0:>11}{shell + voice:>11,}  1")
        print(f"  {'':<30}carries no repository text; same cost on any repo")
    print()


def dump(analysis, which, args):
    """Print one prompt with its slots filled, so you can read what is sent."""
    preview, err = crawl_preview(analysis, args)
    if err:
        sys.exit(f"{analysis}: crawl step failed: {err}")
    for name, slots in SLOTS[analysis].items():
        if which not in name:
            continue
        values = {}
        for slot, kind in slots.items():
            if kind.startswith("crawl-capped-"):
                values[slot] = f"<<{slot}: crawled text, truncated>>"
            elif kind == "model":
                values[slot] = f"<<filled by an earlier LLM call in the run>>"
            elif kind == "bundle":
                values[slot] = "<<the LLM-picked codebase bundle>>"
            elif kind == "small":
                values[slot] = f"<<{slot}>>"
            else:
                values[slot] = "\n".join(preview["files"].get("migrations", [])) \
                    if slot == "migration_names" else f"<<{slot}: crawled text>>"
        print(fill(read_prompt(prompts_dir(analysis), name), **values))
        return
    sys.exit(f"{analysis}: no template matching {which!r}. "
             f"Try one of: {', '.join(SLOTS[analysis])}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run through `uv run`, not a bare python: a bare interpreter can "
               "resolve the editable crawl package to a different checkout.")
    ap.add_argument("repo_path", help="the repository to crawl")
    ap.add_argument("analyses", nargs="*", default=None,
                    help=f"which to measure (default: all). One of: {', '.join(ANALYSES)}")
    ap.add_argument("--codebase-budget", type=int,
                    default=int(os.environ.get("CODEBASE_BUDGET", 650_000)),
                    help="char cap on repository text, as the CLI flag of the same name")
    ap.add_argument("--dump", metavar="TEMPLATE",
                    help="print one prompt with its slots filled, then stop")
    a = ap.parse_args()

    if not os.path.isdir(a.repo_path):
        sys.exit(f"{a.repo_path} is not a directory")
    names = a.analyses or ANALYSES
    for n in names:
        if n not in ANALYSES:
            sys.exit(f"unknown analysis {n!r}. One of: {', '.join(ANALYSES)}")

    args = CrawlArgs(a.repo_path, a.codebase_budget)
    if a.dump:
        if len(names) != 1:
            sys.exit("--dump needs exactly one analysis")
        return dump(names[0], a.dump, args)

    print(f"repo: {a.repo_path}")
    print(f"codebase budget: {a.codebase_budget:,} chars")
    print(f"house style: {len(house_style()):,} chars with the evidence rules, "
          f"{len(house_style(with_evidence=False)):,} without\n")
    for n in names:
        report(n, args)


if __name__ == "__main__":
    main()
