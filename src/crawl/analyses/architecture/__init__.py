"""Map a multi-service architecture in three passes."""

import re
import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.render import Section, Theme, esc, md
from crawl.core.runner import repo_name_of, require_directory, run_analysis
from crawl.core.text import codebase_budget_argument
from .arch_crawl import (DEFAULT_MAX_CHARS, _count_note, build_bundle,
                         manifest_problem_notes)
from crawl.core.preview import Preview, aborts
from .nodes import (BuildBundle, Inventory, TechStack, TraceRequest,
                    empty_bundle_reason)

NAME = "architecture"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"codebase"})

ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

SECTIONS = [
    Section("01", "The inventory",
            "every node, sorted by band: run · rent · call · client",
            "inv", 380, "inventory_md"),
    Section("02", "Tech stack",
            "open each box: the real technology inside the label",
            "tech", 420, "techstack_md"),
    Section("03", "The trace",
            "one request, hop by hop, and how each variant differs",
            "trace", 460, "trace_md"),
]

def _subtitle(shared):
    welcome = (shared.get("overview") or {}).get("welcome", "")
    return (md(welcome) or md(shared.get("shape_verdict", ""))
            or "A multi-service architecture, read three ways.")

def _hero_prefix(shared):
    diagram = shared.get("arch_diagram", "")
    if not diagram:
        return ""
    return ('    <section class="hero-diagram">\n'
            '      <div class="hero-diagram-cap">The whole system on one map</div>\n'
            f'      <div class="diagram"><pre class="mermaid">{esc(diagram)}</pre></div>\n'
            '    </section>\n')

def _footer(shared):
    stats = shared.get("arch_stats", {})
    note = stats.get("sdk_unavailable")
    config_files = stats.get("config_files", 0)
    found = stats.get("config_files_found", config_files)
    excluded = found - config_files
    unreadable_config = _count_note(stats.get("config_files_unreadable", 0),
                                    "config file", "{be} unreadable or refused")
    manifest_notes = manifest_problem_notes(stats.get("manifest_problems", {}))
    unreadable_env = _count_note(stats.get("env_files_unreadable", 0),
                                 "env file", "{be} unreadable or refused")
    truncated_env = _count_note(stats.get("env_files_truncated", 0),
                                "env file", "{be} truncated by the read limit; only what fit was parsed")
    truncated_config = _count_note(stats.get("config_files_truncated", 0),
                                   "config file", "{be} truncated by the read limit; only what fit was parsed")
    return (f"Overlaid from {config_files} config files, "
            f"{stats.get('deps', 0)} dependencies, "
            f"{stats.get('integrations', 0)} integrations."
            + (f" {excluded} more config file{'s' if excluded != 1 else ''} "
               f"{'were' if excluded != 1 else 'was'} found but did not reach the bundle "
               "(empty)." if excluded > 0 else "")
            + (f" {unreadable_config}." if unreadable_config else "")
            + (f" {truncated_config}." if truncated_config else "")
            + "".join(f" {manifest_note}." for manifest_note in manifest_notes)
            + (f" {unreadable_env}." if unreadable_env else "")
            + (f" {truncated_env}." if truncated_env else "")
            + (f" SDK import evidence unavailable ({esc(note)}); connections are configured, not proven live." if note else "")
            + (" SDK import evidence was capped; more imports may exist than are shown."
               if stats.get("sdk_capped") else ""))

def _md_preamble(shared):
    verdict = shared.get("shape_verdict")
    return f"**Shape verdict:** {verdict}\n" if verdict else ""

THEME = Theme(
    title_suffix="architecture", eyebrow="Architecture",
    accent="#d97706", accent_soft="#fffbeb",
    hero_from="#3a2607", hero_to="#1c1203",
    eyebrow_color="#fcd34d", eyebrow_bar="#f59e0b",
    sub_color="#eee0c4", card_top_from="#fffdf7",
    subtitle=_subtitle, footer=_footer, md_preamble=_md_preamble,
    hero_prefix=_hero_prefix,
)

def sent(shared):
    """What left the machine (coderay-3eu): `files` is the config files whole
    (redacted), plus the .env files whose variable names and the package.json
    files whose dependency lists went. `sdk_import_files` are the source files
    git grep matched, of which the path, line number and SDK name went, not the
    line; `integration_dirs` are directory names."""
    return {"files": shared.get("bundle_files", []),
            "sdk_import_files": shared.get("sdk_import_files", []),
            "integration_dirs": shared.get("integration_dirs", [])}


def init_shared(args):
    return {"repo_path": args.repo_path, "codebase_budget": args.codebase_budget}

def build_flow():
    bundle, inventory = BuildBundle(), Inventory()
    tech, trace = TechStack(), TraceRequest()
    overview = OverviewNode(overview_spec)
    bundle >> inventory >> tech >> trace >> overview
    return Flow(start=bundle)

def overview_spec(shared):
    """Analysis-specific bits for the shared OverviewNode (crawl/core/nodes.py)."""
    name = repo_name_of(shared["repo_path"]) or shared["repo_path"]
    n_nodes = len(re.findall(r'^###\s', shared.get("inventory_md", ""), re.MULTILINE))
    return {
        "name": name,
        "what": "a multi-service architecture — the graph of programs and the wires between them",
        "sections": [
            ("The inventory", "every service and store on one map, colour-coded by who runs it"),
            ("Tech stack", "what each box on the map is really built from, behind its label"),
            ("The trace", "which services fire when the product's core request runs, and how variants differ"),
        ],
        "facts": f"{shared.get('shape_verdict', '')} {n_nodes} nodes on the map.",
    }

def add_arguments(parser) -> None:
    parser.add_argument("--codebase-budget", **codebase_budget_argument(DEFAULT_MAX_CHARS))

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call. This bundle overlays
    process declarations, env var names, declared dependencies, infrastructure
    config and SDK import lines, so it counts each of those rather than a single
    included set. Env var names and SDK import lines are the two largest drivers
    of bundle size, which is why they are reported here and not only by the run."""
    bundle, stats = build_bundle(args.repo_path, max_chars=args.codebase_budget)
    counts = {
        # The bundle carries env files and dependency manifests too, so its own
        # length is reported beside the config-only count rather than standing in
        # for it; the two describe different populations.
        "files in the bundle": len(stats["files"]),
        "config files in the bundle": stats["config_files"],
        "config files found": stats["config_files_found"],
        "config files unreadable": stats["config_files_unreadable"],
        "config files truncated": stats["config_files_truncated"],
        "env files unreadable": stats["env_files_unreadable"],
        "env files truncated": stats["env_files_truncated"],
        "env var names": stats["env_vars"],
        "dependencies declared": stats["deps"],
        "integration directories": stats["integrations"],
        "SDK import lines": stats["sdk_lines"],
    }
    notes = list(manifest_problem_notes(stats["manifest_problems"]))
    if stats["truncated"]:
        # This crawler caps the assembled text rather than dropping files, so
        # the counts above would otherwise overstate what the model reads.
        notes.append(f"The bundle was truncated at the {args.codebase_budget:,}-char budget; "
                     "the model sees less than the counts above describe.")
    if stats["sdk_unavailable"]:
        # The reason, not a flag: "not a git repository" and "git is not
        # installed" are different problems and only one is the user's to fix.
        notes.append(f"SDK import evidence unavailable ({stats['sdk_unavailable']}); "
                     "connections are configured, not proven live.")
    if stats["sdk_capped"]:
        notes.append("SDK import evidence was capped; more imports may exist than are counted.")
    if not bundle.strip():
        notes.append(aborts(empty_bundle_reason(stats["sdk_unavailable"])))
    # No `dropped`: this crawler caps its assembled text rather than dropping
    # whole files, so there is no dropped set to name. A zero here would be a
    # count no crawler computed (coderay-05w.6); the truncation note carries
    # what the counts alone would misstate.
    return {"counts": counts, "files": {"bundle": stats["files"]},
            "included": stats["files"], "assembled_chars": len(bundle), "notes": notes}


def run(args) -> None:
    require_directory(args.repo_path)
    run_analysis(sys.modules[__name__], args)
