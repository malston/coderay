"""Map a multi-service architecture in three passes (ch09)."""

import os
import re
import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.render import Section, Theme, esc, md
from crawl.core.runner import repo_name_of, run_analysis
from .nodes import BuildBundle, Inventory, TechStack, TraceRequest

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
    return (f"Overlaid from {stats.get('config_files', 0)} config files, "
            f"{stats.get('deps', 0)} dependencies, "
            f"{stats.get('integrations', 0)} integrations."
            + (f" SDK import evidence unavailable ({note}); connections are configured, not proven live." if note else ""))

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

def init_shared(args):
    return {"repo_path": args.repo_path}

def build_flow():
    bundle, inventory = BuildBundle(), Inventory()
    tech, trace = TechStack(), TraceRequest()
    overview = OverviewNode(overview_spec)
    bundle >> inventory >> tech >> trace >> overview
    return Flow(start=bundle)

def overview_spec(shared):
    """Chapter-specific bits for the shared OverviewNode (crawl/core/nodes.py)."""
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
    """The architecture analysis takes no flags beyond the common repo_path/--out."""

def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
