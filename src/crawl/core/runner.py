"""Runs a pipeline flow against a shared state dict, common to any analysis."""
import os

from .env import env_defaults
from .render import render_html, render_markdown

def run_flow(flow, shared, out_dir, dump_state):
    """Run `flow` against `shared`. On an unhandled exception, call
    `dump_state(shared, out_dir)` to write whatever partial progress exists,
    print where it landed, and re-raise."""
    try:
        flow.run(shared)
    except (Exception, SystemExit):
        state_path = dump_state(shared, out_dir)
        print(f"\nPipeline failed. Wrote partial run state to {state_path}")
        raise

def repo_name_of(repo_path):
    """The repo's directory name, used for the output folder and the page title.

    One helper so the name the overview prompt is given always matches the name
    rendered on the page. Resolving to an absolute path first keeps a relative
    repo_path (".", "../thing/") from yielding a useless name."""
    return os.path.basename(os.path.abspath(repo_path))

def default_output_dir(repo_path, analysis_name):
    """Anchored on the current working directory, not this file's location, so
    output lands in the same place whether crawl runs from an editable checkout
    or as an installed tool."""
    name = repo_name_of(repo_path)
    return os.path.join(os.getcwd(), "output", f"{name}-{analysis_name}")

def run_analysis(analysis, args):
    """Run one analysis and write its index.md and index.html. Returns out_dir.

    The output directory is created before the flow runs, because an analysis
    may write extra files into it during the run."""
    out_dir = args.out or default_output_dir(args.repo_path, analysis.NAME)
    os.makedirs(out_dir, exist_ok=True)

    name = repo_name_of(args.repo_path)
    shared = analysis.init_shared(args)
    with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
        analysis.build_flow().run(shared)

    with open(os.path.join(out_dir, "index.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(analysis, name, shared))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(analysis, name, shared))

    print(f"\nWrote {analysis.NAME} to {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser")
    return out_dir
