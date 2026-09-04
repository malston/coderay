"""tour: the default analysis. Crawls a repo, extracts a deterministic import
graph, identifies abstractions, relates them, and writes a multi-chapter tour."""
import os
import time
from datetime import date

from crawl.core import ensure_priced, get_usage, reset_usage, resolve_provider_and_model
from crawl.core.env import env_defaults
from crawl.core.runner import run_flow
from crawl.analyses.tour.flow import create_tour_flow
from crawl.analyses.tour.nodes import PipelineState
from crawl.analyses.tour.render import (
    available_lenses,
    build_mermaid,
    default_output_dir,
    dump_run_state,
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

# A chapter can run past the 16384-token default on a large abstraction
# (coderay-q2r.46); backend raises its cap the same way.
ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}

def init_shared(args) -> PipelineState:
    return {"repo_path": args.repo_path, "instructions": args.instructions}

def run(args) -> None:
    # Exit code 1, no usage line -- not the same as argparse's ap.error() (code 2,
    # usage printed), a sanctioned exception (see Global Constraints): run(args)
    # has no parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")

    if args.dry_run:
        try:
            provider, model = resolve_provider_and_model()
        except RuntimeError:
            provider, model = "anthropic", "claude-sonnet-5"
        print(format_dry_run_summary(estimate_dry_run_cost(args.repo_path, args.instructions, provider, model)))
        return

    provider, model = resolve_provider_and_model()
    ensure_priced(provider, model)

    name = os.path.basename(os.path.abspath(args.repo_path))
    out = args.out or default_output_dir(args.repo_path, args.instructions)
    os.makedirs(out, exist_ok=True)

    reset_usage()
    wall_start = time.perf_counter()

    shared = init_shared(args)
    with env_defaults(ENV_DEFAULTS):
        run_flow(build_flow(), shared, out, dump_run_state)

    wall_seconds = time.perf_counter() - wall_start

    chapters = shared["chapters"]
    mermaid = build_mermaid(shared["abstractions"], shared["relationships"])

    generated_at = date.today().isoformat()
    write_chapter_files(chapters, name, out, shared["relationships"], generated_at)
    write_index_md(chapters, name, args.instructions, shared["summary"], mermaid, out, generated_at)
    write_index_html(
        chapters, name, args.instructions, shared["summary"], mermaid,
        shared["selected_files"], shared["selection_reasoning"], out, generated_at,
    )

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")
    print()
    print(format_session_summary(get_usage(), wall_seconds))
