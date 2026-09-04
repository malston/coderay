"""Map the API surface and trace one action through it (ch08)."""

import os
import re
import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.render import (
    Section, Theme, card, esc, extract_mermaid, md, strip_mermaid)
from crawl.core.runner import repo_name_of, run_analysis
from .nodes import FindRoutes, ApiMenu, TraceActions, EndpointSequence

NAME = "interfaces"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"routes"})

ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

def _sequence_prefix(shared):
    diagram = extract_mermaid(shared.get("sequence_md", ""))
    return (f'    <div class="diagram"><pre class="mermaid">{esc(diagram)}</pre></div>\n'
            if diagram else "")

UNGROUNDED_NOTE = (
    "**No handler source was read for this endpoint.** The diagram below was "
    "written from the route list alone, so its steps and any `file:line` "
    "references are the model's inference, not something it read.")

def _code(name):
    """A markdown code span around a file name, fenced with one more backtick
    than the longest run inside it, so a backtick in the name cannot end the
    span early and `__init__.py` is not read as emphasis. The renderer's
    markdown-it runs with html=False, so the span's content is escaped there."""
    longest = max((len(m) for m in re.findall(r"`+", name)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if name.startswith("`") or name.endswith("`") else ""
    return f"{fence}{pad}{name}{pad}{fence}"


def _source_note(shared):
    """The sentence that says which source the diagram was drawn from when it
    was not the source the model named (coderay-5wu.1). Called only for a
    grounded diagram; the ungrounded note takes precedence upstream. What
    differs here is whose source was read, not whether any was. "Not read"
    covers every reason read_files leaves a path out (missing, empty, past the
    file cap, over the size budget, refused), so the card never claims a file
    does not exist."""
    fallback = shared.get("sequence_fallback")
    dropped = shared.get("sequence_dropped") or []
    dropped = [_code(p) for p in (dropped if isinstance(dropped, list) else [])]
    if fallback and dropped:
        return (f"**Drawn from {_code(fallback)}, not the files the model named** "
                f"({', '.join(dropped)}), none of which could be read.")
    if fallback:
        return (f"**The model named no source files.** The diagram is drawn from "
                f"{_code(fallback)}, the largest route file.")
    if dropped:
        n = len(dropped)
        return (f"**{n} of the files the model named {'was' if n == 1 else 'were'} not read** "
                f"({', '.join(dropped)}); the diagram is drawn from the rest.")
    return ""


def _sequence_cards(shared, body_md):
    """One hand-built card holding the sequence body, with the fence removed.

    When no handler source reached the prompt the diagram is inference, and it
    renders identically to a grounded one, so say so in the card rather than
    only on stdout (coderay-q2r.25). The same goes for source that exists but
    is not what the model named (coderay-5wu.1). A reply that is a fence and
    nothing else leaves an empty body; the card still renders when there is a
    note to carry, and is omitted only when there is nothing to say."""
    body = strip_mermaid(body_md)
    note = UNGROUNDED_NOTE if not shared.get("sequence_grounded", True) else _source_note(shared)
    if not body and not note:
        return ""
    if note:
        body = note + ("\n\n" + body if body else "")
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
    found = len(shared.get("route_files", []))
    # route_files_read is what reached the bundle; the rest were dropped by the
    # size cap or read empty. Saying "read from N found files" overstates the
    # provenance of the whole report (coderay-q2r.24).
    read = len(shared.get("route_files_read", shared.get("route_files", [])))
    of_found = "" if read == found else f" of {found} found"
    return (f"Read from {read} route files{of_found} &middot; "
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
    """Chapter-specific bits for the shared OverviewNode (crawl/core/nodes.py)."""
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
