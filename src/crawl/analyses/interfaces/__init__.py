"""Map the API surface and trace one action through it."""

import re
import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.render import (
    Section, Theme, card, esc, extract_mermaid, md, strip_mermaid)
from crawl.core.runner import repo_name_of, require_directory, run_analysis
from crawl.core.text import codebase_budget_argument
from .routes_find import DEFAULT_MAX_CHARS, crawl_routes
from crawl.core.preview import Preview, aborts
from crawl.core.estimate import Prompt, overview_prompt, shell_chars
from .nodes import (FindRoutes, ApiMenu, TraceActions, EndpointSequence,
                    NO_SURFACE)

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


def _sequence_note(shared):
    """Which note, if any, belongs beside the sequence diagram: the q2r.25
    ungrounded warning takes precedence, then the 5wu.1 fallback-source note.
    Shared between the HTML card and the markdown section's md_note hook so
    both pages say the same thing (coderay-5wu.10)."""
    if not shared.get("sequence_grounded", True):
        return UNGROUNDED_NOTE
    return _source_note(shared)


def _sequence_cards(shared, body_md):
    """One hand-built card holding the sequence body, with the fence removed.

    When no handler source reached the prompt the diagram is inference, and it
    renders identically to a grounded one, so say so in the card rather than
    only on stdout (coderay-q2r.25). The same goes for source that exists but
    is not what the model named (coderay-5wu.1). A reply that is a fence and
    nothing else leaves an empty body; the card still renders when there is a
    note to carry, and is omitted only when there is nothing to say."""
    body = strip_mermaid(body_md)
    note = _sequence_note(shared)
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
            prefix=_sequence_prefix, cards=_sequence_cards, md_note=_sequence_note),
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

def sent(shared):
    """What left the machine: the route files read into the surface bundle and
    the source files the sequence view read on the model's pick, each once (coderay-3eu)."""
    files = list(shared.get("route_files_read", []))
    files += [f for f in shared.get("sequence_files", []) if f not in files]
    return {"files": files}


def init_shared(args):
    return {"repo_path": args.repo_path, "codebase_budget": args.codebase_budget}

def build_flow():
    find, menu = FindRoutes(), ApiMenu()
    trace, seq = TraceActions(), EndpointSequence()
    overview = OverviewNode(overview_spec)
    find >> menu >> trace >> seq >> overview
    return Flow(start=find)

def overview_spec(shared):
    """Analysis-specific bits for the shared OverviewNode (crawl/core/nodes.py)."""
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
    parser.add_argument("--codebase-budget", **codebase_budget_argument(DEFAULT_MAX_CHARS))

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call: the surface files found by
    convention, and the ones whose text actually reached the bundle. A found file
    is left out when it is empty or would not fit the budget (coderay-q2r.24), and
    is named as well as counted (coderay-05w.4)."""
    routes, found, read = crawl_routes(args.repo_path, max_chars=args.codebase_budget)
    reached = set(read)
    dropped = [rel for rel in found if rel not in reached]
    notes = []
    if dropped:
        notes.append(f"{len(dropped)} of {len(found)} surface files "
                     "did not reach the bundle: empty, or past the budget.")
    if not routes.strip():
        notes.append(aborts(NO_SURFACE))
    return {"counts": {"surface files found": len(found), "surface files read": len(read)},
            "files": {"found": found, "read": read, "did not reach the bundle": dropped},
            "included": read, "dropped": dropped, "assembled_chars": len(routes), "notes": notes}



def prompt_plan(args, preview):
    """Four prompts plus the overview. EndpointSequence sends two: an inline
    pick, then the diagram. The diagram prompt also carries the source files the
    pick named, read back off disk, which no pre-flight step can size."""
    from .nodes import PROMPTS_DIR, ROUTES_CAP, _PICK_PROMPT
    body = preview.get("assembled_chars") or 0
    return [
        Prompt("api-menu.md", shell_chars(PROMPTS_DIR, "api-menu.md", ("routes",)),
               body, (1, 1)),
        Prompt("trace-action.md",
               shell_chars(PROMPTS_DIR, "trace-action.md", ("routes", "groups")),
               body, (1, 1)),
        Prompt("_PICK_PROMPT (inline)",
               len(_PICK_PROMPT) - len("{menu}") - len("{routes}"), body, (1, 1)),
        Prompt("endpoint-sequence.md",
               shell_chars(PROMPTS_DIR, "endpoint-sequence.md",
                           ("routes", "flow", "handler_source")),
               min(body, ROUTES_CAP), (1, 1),
               note="endpoint-sequence.md also carries the handler source the pick "
                    "names, read back off disk; no pre-flight step can size it"),
    ] + [overview_prompt()]


def run(args) -> None:
    require_directory(args.repo_path)
    run_analysis(sys.modules[__name__], args)
