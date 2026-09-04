"""Runs a pipeline flow against a shared state dict, common to any analysis."""
import json
import os
import sys

from .env import env_defaults
from .render import render_html, render_markdown

def run_flow(flow, shared, out_dir, dump_state):
    """Run `flow` against `shared`. On an unhandled exception, call
    `dump_state(shared, out_dir)` to write whatever partial progress exists,
    say where it landed on stderr beside the traceback, and re-raise. A dump
    that fails is reported the same way and the pipeline's own error is still
    the one that propagates."""
    try:
        flow.run(shared)
    except (Exception, SystemExit):
        try:
            state_path = dump_state(shared, out_dir)
        except (OSError, TypeError, ValueError) as e:
            print(f"\nPipeline failed, and the partial run state could not be written to {out_dir}: {e}",
                  file=sys.stderr)
        else:
            print(f"\nPipeline failed. Wrote partial run state to {state_path}", file=sys.stderr)
        raise

def dump_run_state(shared, out_dir, skip=frozenset()):
    """Write `shared`, minus the keys in `skip`, to run_state.json in out_dir
    and return the path.

    Every LLM result a pipeline has produced so far lives in `shared`, so this
    is what the user gets back when a later node fails (coderay-q2r.49). The
    caller passes the pipeline's input keys as `skip`: the source bundle is
    free to regenerate and can be most of a megabyte. Values JSON cannot
    represent are written as their str(). Serialised in full before the file
    is opened, so a serialisation error cannot leave a truncated file."""
    text = json.dumps({k: v for k, v in shared.items() if k not in skip}, indent=2, default=str)
    path = os.path.join(out_dir, "run_state.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


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

def write_report(analysis, name, shared, out_dir):
    """Render the analysis and write index.md and index.html into out_dir.

    The one write path for a real run and for the golden fixtures, so the two
    cannot drift. Returns out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(analysis, name, shared))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(analysis, name, shared))
    return out_dir


def run_analysis(analysis, args):
    """Run one analysis and write its index.md and index.html. Returns out_dir.

    The output directory is created before the flow runs, because an analysis
    may write extra files into it during the run. If the flow raises, whatever
    it added to `shared` is written to run_state.json there and the exception
    propagates; a state file left by an earlier failed run is removed first,
    since the default output directory is the same run to run."""
    out_dir = args.out or default_output_dir(args.repo_path, analysis.NAME)
    os.makedirs(out_dir, exist_ok=True)
    stale = os.path.join(out_dir, "run_state.json")
    if os.path.exists(stale):
        os.remove(stale)

    name = repo_name_of(args.repo_path)
    shared = analysis.init_shared(args)
    inputs = frozenset(shared)
    with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
        run_flow(analysis.build_flow(), shared, out_dir,
                 lambda s, o: dump_run_state(s, o, skip=inputs))

    write_report(analysis, name, shared, out_dir)

    print(f"\nWrote {analysis.NAME} to {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser")
    return out_dir
