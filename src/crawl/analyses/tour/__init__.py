"""tour: the default analysis. Crawls a repo, extracts a deterministic import
graph, identifies abstractions, relates them, and writes a multi-chapter tour."""
import os
import time
from datetime import date

from crawl.core import ensure_priced, get_usage, reset_usage, resolve_provider_and_model
from crawl.core.env import env_defaults
from crawl.core.text import codebase_budget_argument
from crawl.core.runner import (keeping_results, require_directory, run_flow,
                                run_state_writer, write_manifest)
from crawl.analyses.tour.flow import create_tour_flow
from crawl.analyses.tour.nodes import (CODEBASE_BUDGET, NO_SOURCE,
                                       PREVIEW_CHARS_PER_FILE, PipelineState,
                                       SmartCrawl)
from crawl.core.preview import Preview, aborts
from crawl.analyses.tour.render import (
    available_lenses,
    build_mermaid,
    default_output_dir,
    estimate_dry_run_cost,
    format_dry_run_summary,
    format_session_summary,
    write_chapter_files,
    write_index_html,
    write_index_md,
)

NAME = "tour"

def build_flow():
    return create_tour_flow()

def add_arguments(parser) -> None:
    parser.add_argument("--instructions", default="beginner-tutorial", choices=available_lenses())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--codebase-budget", **codebase_budget_argument(CODEBASE_BUDGET))

# A chapter can run past the 16384-token default on a large abstraction
# (coderay-q2r.46); backend raises its cap the same way.
ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

# Left out of the failure dump: the assembled source and the import graph
# both regenerate without an LLM call, and the source can be a megabyte.
INPUT_KEYS = frozenset({"codebase", "symbol_graph"})

def sent(shared):
    """What left the machine: the selected files, whole, and every file whose
    preview went into the selection prompt (coderay-3eu)."""
    return {"files": shared.get("selected_files", []), "previewed_files": shared.get("previewed_files", [])}


def preview(args) -> Preview:
    """What the crawl step found, before any LLM call: every file whose head goes
    into the file-selection prompt, and every file the preview cap kept out of it.

    "Source files found" is what list_files returned, not what is on disk: it has
    already dropped unrecognised extensions, skipped directories and anything over
    the size ceiling.
    The model cannot pick a file it never saw, so the cap is the number that
    decides whether this analysis reads the repo or a slice of it.

    Reuses SmartCrawl's own prep(), which records both figures on `shared`,
    rather than rebuilding its preview-manifest logic here.

    --codebase-budget is accepted and does not move these counts: it sizes the
    analyze, relate and chapter prompts, which no file crawl reaches."""
    shared = init_shared(args)
    try:
        SmartCrawl().prep(shared)
    except SystemExit as no_source:
        return {"counts": {"source files found": 0, "read into the selection pass": 0,
                           "dropped before the model saw them": 0},
                "files": {"previewed": [], "dropped before the model saw them": []},
                "included": [], "dropped": [], "assembled_chars": 0,
                "notes": [aborts(str(no_source))]}
    previewed = shared["previewed_files"]
    dropped = shared["preview_dropped_files"]
    found = shared["source_files_found"]
    notes = []
    if dropped:
        notes.append(
            f"{len(dropped):,} of {found:,} source files never reach the file-selection "
            f"prompt: it holds {len(previewed):,} at {PREVIEW_CHARS_PER_FILE:,} chars "
            "each. The model cannot pick a file it never saw.")
    # assembled_chars is the manifest, not the codebase bundle: the bundle is
    # built in SmartCrawl.post from the files the model picks, which no preview
    # can know. The manifest is the text this crawl step actually assembled.
    return {"counts": {"source files found": found,
                       "read into the selection pass": len(previewed),
                       "dropped before the model saw them": len(dropped)},
            "files": {"previewed": previewed, "dropped before the model saw them": dropped},
            "included": previewed, "dropped": dropped,
            "assembled_chars": shared["preview_manifest_chars"], "notes": notes}



def init_shared(args) -> PipelineState:
    return {"repo_path": args.repo_path, "instructions": args.instructions,
            "codebase_budget": args.codebase_budget}

def run(args) -> None:
    require_directory(args.repo_path)

    if args.dry_run:
        try:
            provider, model = resolve_provider_and_model()
        except RuntimeError:
            provider, model = "anthropic", "claude-sonnet-5"
        # The real run below applies ENV_DEFAULTS for the whole flow, so the
        # estimate must see the same LLM_MAX_OUTPUT_TOKENS or its worst-case
        # bound is half of what a real run could actually hit (coderay-5wu.26).
        with env_defaults(ENV_DEFAULTS):
            print(format_dry_run_summary(estimate_dry_run_cost(
                args.repo_path, args.instructions, provider, model, codebase_budget=args.codebase_budget)))
        return

    provider, model = resolve_provider_and_model()
    ensure_priced(provider, model)

    name = os.path.basename(os.path.abspath(args.repo_path))
    out = args.out or default_output_dir(args.repo_path, args.instructions)
    os.makedirs(out, exist_ok=True)

    reset_usage()
    wall_start = time.perf_counter()

    shared = init_shared(args)
    dump_run_state = run_state_writer(out, shared, INPUT_KEYS)
    with env_defaults(ENV_DEFAULTS):
        run_flow(build_flow(), shared, out, dump_run_state)

    def write_tour():
        chapters = shared["chapters"]
        mermaid = build_mermaid(shared["abstractions"], shared["relationships"])
        generated_at = date.today().isoformat()
        write_chapter_files(chapters, name, out, shared["relationships"], generated_at)
        write_index_md(chapters, name, args.instructions, shared["summary"], mermaid, out, generated_at)
        write_index_html(
            chapters, name, args.instructions, shared["summary"], mermaid,
            shared["selected_files"], shared["selection_reasoning"], out, generated_at,
        )
        write_manifest(NAME, name, sent(shared), out, get_usage())

    # shared holds every paid result by now; a failed write, or an interrupt,
    # keeps it as a failed node would.
    keeping_results(write_tour, shared, out, dump_run_state)
    wall_seconds = time.perf_counter() - wall_start

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")
    print()
    print(format_session_summary(get_usage(), wall_seconds))
