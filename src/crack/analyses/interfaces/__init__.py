"""Map the API surface and trace one action through it (ch08)."""

import os
import re
import sys

from pocketflow import Flow

from crack.core import OverviewNode
from crack.core.render import (
    Section, Theme, card, esc, extract_mermaid, md, strip_mermaid)
from crack.core.runner import repo_name_of, run_analysis
from .nodes import FindRoutes, ApiMenu, TraceActions, EndpointSequence

NAME = "interfaces"

ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

def _sequence_prefix(shared):
    diagram = extract_mermaid(shared.get("sequence_md", ""))
    return (f'    <div class="diagram"><pre class="mermaid">{esc(diagram)}</pre></div>\n'
            if diagram else "")

def _sequence_cards(shared, body_md):
    """One hand-built card holding the sequence body, with the fence removed."""
    body = strip_mermaid(body_md)
    if not body:
        return ""
    return card(esc(shared.get("sequence_endpoint") or "Sequence"), body)

SECTIONS = [
    Section("01", "Feature menu",
            "every endpoint, grouped by feature, biggest first",
            "menu", 380, "groups_md"),
    Section("02", "The tour",
            "the groups that say the most about the product",
            "tour", 380, "tour_md", when_empty="omit"),
    Section("03", "Action flows",
            "one gesture, every lane it touches, in order",
            "flows", 440, "flows_md"),
    Section("04", "Endpoint sequence",
            "one endpoint, every message inside it",
            "seq", 560, "sequence_md",
            prefix=_sequence_prefix, cards=_sequence_cards),
]

def _subtitle(shared):
    welcome = (shared.get("overview") or {}).get("welcome", "")
    return (md(welcome) or md(shared.get("opener", ""))
            or "The API surface, read three ways.")

def _hero_prefix(shared):
    """Feature groups sized by endpoint count, parsed out of the group names."""
    groups = []
    for name in shared.get("group_names", []):
        m = re.match(r'(.+?)\s*\((\d+)', name)
        if m:
            groups.append((m.group(1).strip(), int(m.group(2))))
    if not groups:
        return ""
    biggest = max(n for _, n in groups) or 1
    rows = "".join(
        f'<div class="gc-row"><div class="gc-name">{esc(name)}</div>'
        f'<div class="gc-track"><div class="gc-bar" '
        f'style="width:{max(7, round(n / biggest * 100))}%">{n}</div></div></div>'
        for name, n in groups)
    total = sum(n for _, n in groups)
    return (
        '    <section class="hero-diagram">\n'
        f'      <div class="hero-diagram-cap">The API surface at a glance &mdash; '
        f'{total} endpoints across {len(groups)} feature groups</div>\n'
        f'      <div class="groupchart">{rows}</div>\n'
        '    </section>\n'
    )

def _footer(shared):
    return (f"Read from {len(shared.get('route_files', []))} route files &middot; "
            f"{len(shared.get('group_names', []))} feature groups.")

def _md_preamble(shared):
    opener = shared.get("opener")
    return opener.strip() + "\n" if opener else ""

THEME = Theme(
    title_suffix="interfaces", eyebrow="Interfaces",
    accent="#0d9488", accent_soft="#effcf9",
    hero_from="#0f3d38", hero_to="#06201d",
    eyebrow_color="#5eead4", eyebrow_bar="#2dd4bf",
    sub_color="#cbeee7", card_top_from="#f6fdfb",
    subtitle=_subtitle, footer=_footer, md_preamble=_md_preamble,
    hero_prefix=_hero_prefix,
)

def init_shared(args):
    return {"repo_path": args.repo_path}

def build_flow():
    find, menu = FindRoutes(), ApiMenu()
    trace, seq = TraceActions(), EndpointSequence()
    overview = OverviewNode(overview_spec)
    find >> menu >> trace >> seq >> overview
    return Flow(start=find)

def overview_spec(shared):
    """Chapter-specific bits for the shared OverviewNode (crack/core/nodes.py)."""
    name = repo_name_of(shared["repo_path"]) or shared["repo_path"]
    return {
        "name": name,
        "what": "a product's API surface — every door into the system",
        "sections": [
            ("Feature menu", "every endpoint grouped by feature, biggest group first, each tagged public/user/admin"),
            ("The tour", "a short walk through the groups that say the most about the product"),
            ("Action flows", "which services fire, in order, for one user gesture"),
            ("Endpoint sequence", "a message-by-message diagram of one endpoint, request to response"),
        ],
        "facts": (f"{shared.get('opener', '')[:400]} "
                  f"{len(shared.get('group_names', []))} feature groups. "
                  f"Endpoint diagrammed: {shared.get('sequence_endpoint', '')}."),
    }


def add_arguments(parser) -> None:
    """The interfaces analysis takes no flags beyond the common repo_path/--out."""

def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
