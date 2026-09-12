"""Tour the data model and the migrations that shaped it."""

import sys

from pocketflow import Flow

from crawl.core import OverviewNode
from crawl.core.render import Section, Theme, esc, md
from crawl.core.runner import repo_name_of, require_directory, run_analysis
from crawl.core.text import codebase_budget_argument
from .schema_find import (SCHEMA_BUDGET, TRUNCATION_MARKER, find_migrations,
                          find_schema)
from crawl.core.preview import Preview, aborts
from .nodes import (FindSchema, SchemaTour, TraceFlows, TableDeepDive,
                    MigrationActs, MIGRATION_FLOOR, NO_SCHEMA)

NAME = "schema"
# What the first node reads from the repo; left out of run_state.json on failure.
INPUT_KEYS = frozenset({"schema"})

ENV_DEFAULTS = {}

def _migration_skip_note(shared):
    n = len(shared.get("migration_names", []))
    if n < MIGRATION_FLOOR:
        return (f"skipped &mdash; only {n} migrations found "
                "(too few, or history squashed)")
    return f"no acts written &mdash; the pass over {n} migrations produced none"

def _migration_md_skip_note(shared):
    n = len(shared.get("migration_names", []))
    if n < MIGRATION_FLOOR:
        return f"_Skipped: only {n} migrations found._\n"
    return f"_No acts written: the pass over {n} migrations produced none._\n"

SECTIONS = [
    Section("01", "The tour",
            "the schema as a story, one cluster at a time",
            "tour", 400, "tour_md"),
    Section("02", "The flows",
            "one user action, many tables, in order",
            "flows", 400, "flows_md"),
    Section("03", "Table deep dive",
            "columns are decisions, indexes are the hot queries",
            "deep", 480, "deepdive_md"),
    Section("04", "Migration history",
            "the roadmap the live schema erases",
            "acts", 420, "migration_md",
            when_empty="skip-note",
            skip_note=_migration_skip_note,
            md_skip_note=_migration_md_skip_note),
]

def _page_name(shared, name):
    return shared.get("product_name") or name

def _subtitle(shared):
    welcome = (shared.get("overview") or {}).get("welcome", "")
    return (md(welcome) or md(shared.get("one_liner", ""))
            or "The data model, read four ways.")

def _hero_prefix(shared):
    erd = shared.get("erd", "")
    if not erd:
        return ""
    n_tables = len(shared.get("table_list", []))
    return ('    <section class="hero-diagram">\n'
            f'      <div class="hero-diagram-cap">The whole schema at a glance &mdash; '
            f'{n_tables} core tables and how they connect</div>\n'
            f'      <div class="diagram"><pre class="mermaid">{esc(erd)}</pre></div>\n'
            '    </section>\n')

def _footer(shared):
    return (f"Read from {esc(shared.get('schema_path', ''))} &middot; "
            f"{len(shared.get('table_list', []))} core tables &middot; "
            f"{len(shared.get('migration_names', []))} migrations.")

def _md_preamble(shared):
    one_liner = shared.get("one_liner")
    return f"_{one_liner}_\n" if one_liner else ""

THEME = Theme(
    title_suffix="schema", eyebrow="Schema",
    accent="#6941c6", accent_soft="#f4f0ff",
    hero_from="#2b1c4d", hero_to="#12091f",
    eyebrow_color="#c4b5fd", eyebrow_bar="#a78bfa",
    sub_color="#d6cff0", card_top_from="#fbfaff",
    subtitle=_subtitle, footer=_footer, md_preamble=_md_preamble,
    hero_prefix=_hero_prefix, page_name=_page_name,
)

def add_arguments(parser):
    parser.add_argument("--schema", default=None,
                        help="path to the schema file, relative to the repo "
                             "(overrides autodetect)")
    parser.add_argument("--codebase-budget", **codebase_budget_argument(SCHEMA_BUDGET))

def preview(args) -> Preview:
    """What the crawl step found, before any LLM call: the schema files read (by
    convention, or named by --schema) and the migration directory with the most
    timestamped entries.

    find_schema names a file before it reads it, so a --schema path that is
    missing, unreadable or refused comes back named with empty text. Counting the
    name would report a file this command never read."""
    schema = find_schema(args.repo_path, args.schema, args.codebase_budget)
    _mig_dir, mig_names = find_migrations(args.repo_path)
    read = schema["files"] if schema["text"] else []
    notes = []
    if schema["files"] and not schema["text"]:
        notes.append(f"{schema['path']} could not be read: missing, unreadable, "
                     "or refused as credential-named.")
    elif TRUNCATION_MARKER in schema["text"]:
        notes.append(f"The schema was truncated at the {args.codebase_budget:,}-char budget; "
                     "the model reads less than the whole file.")
    if read:
        notes.append(f"Schema read from {schema['path']} ({schema['kind']}).")
    else:
        notes.append(aborts(NO_SCHEMA))
    if mig_names and len(mig_names) < MIGRATION_FLOOR:
        notes.append(f"{len(mig_names)} migrations is below the floor of {MIGRATION_FLOOR}; "
                     "a real run skips the migration pass entirely.")
    return {"counts": {"schema files read": len(read), "migrations found": len(mig_names)},
            "files": {"schema": read, "migrations": mig_names}, "notes": notes}


def sent(shared):
    """What left the machine: the schema files read, and the names (not the
    bodies) of the migrations the acts prompt listed; below MIGRATION_FLOOR
    that prompt is never built and none go (coderay-3eu)."""
    return {"files": shared.get("schema_files", []), "migration_names": shared.get("migrations_sent", [])}


def init_shared(args):
    return {"repo_path": args.repo_path,
            "schema_override": getattr(args, "schema", None),
            "codebase_budget": args.codebase_budget}

def build_flow():
    find, tour = FindSchema(), SchemaTour()
    flows, deep = TraceFlows(), TableDeepDive()
    migrations = MigrationActs()
    overview = OverviewNode(overview_spec)
    find >> tour >> flows >> deep >> migrations >> overview
    return Flow(start=find)

def overview_spec(shared):
    """The analysis-specific bits the shared OverviewNode needs (see crawl/core/nodes.py)."""
    name = shared.get("product_name") or repo_name_of(shared["repo_path"]) or shared["repo_path"]
    return {
        "name": name,
        "what": "a database schema as a map of the business",
        "sections": [
            ("The tour", "the schema told as a story, one cluster of tables at a time, with a diagram"),
            ("The flows", "which tables a single user action reads and writes, in order"),
            ("Table deep dive", "the columns and indexes that carry each table's real decisions"),
            ("Migration history", "the product eras the live schema hides"),
        ],
        "facts": (f"{name}: {shared.get('one_liner', '')}. "
                  f"{len(shared.get('table_list', []))} core tables, "
                  f"{len(shared.get('migration_names', []))} migrations."),
    }


def run(args) -> None:
    require_directory(args.repo_path)
    run_analysis(sys.modules[__name__], args)
