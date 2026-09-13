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
from crawl.core.estimate import Prompt, shell_chars
from crawl.analyses.tour.render import (
    available_lenses,
    build_mermaid,
    default_output_dir,
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


def prompt_plan(args, preview):
    """Five prompts. The file-selection prompt is sized from the manifest the
    preview measured. The other three carry the codebase bundle, which is built
    from files the model picks, so no pre-flight step can size it: they are
    estimated from the same reader _codebase_preview_text uses, with a note
    saying so (coderay-3le)."""
    from .nodes import CHAPTER_RANGE, PROMPTS_DIR, load_instructions
    from .render import _codebase_preview_text
    bundle = len(_codebase_preview_text(args.repo_path, args.codebase_budget))
    # The lens fills {instructions} in every chapter prompt, and the lenses
    # differ by hundreds of bytes, so --instructions moves this number.
    lens = len(load_instructions(args.instructions))
    guess = ("the codebase bundle is built from files the model picks; this sizes it "
             "from every readable file up to the budget, which overstates it "
             "(coderay-3le)")
    return [
        Prompt("select-files.md",
               shell_chars(PROMPTS_DIR, "select-files.md",
                           ("manifest", "target_count", "chars_per_file")),
               preview.get("assembled_chars") or 0, (1, 1)),
        Prompt("identify-abstractions.md",
               shell_chars(PROMPTS_DIR, "identify-abstractions.md",
                           ("codebase", "selected_files")),
               bundle, (1, 1), note=guess),
        Prompt("analyze-relationships.md",
               shell_chars(PROMPTS_DIR, "analyze-relationships.md",
                           ("codebase", "abstractions")),
               bundle, (1, 1)),
        Prompt("write-chapter.md",
               shell_chars(PROMPTS_DIR, "write-chapter.md",
                           ("codebase", "instructions", "name", "description",
                            "chapter_num", "total", "prev_chapters", "chapter_list")),
               bundle + lens, CHAPTER_RANGE,
               note=f"one call per chapter; identify-abstractions.md asks for "
                    f"{CHAPTER_RANGE[0]} to {CHAPTER_RANGE[1]} abstractions"),
    ]


def run(args) -> None:
    require_directory(args.repo_path)

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
