"""Runs a pipeline flow against a shared state dict, common to any analysis."""
import json
import os
import sys

from .env import env_defaults
from .render import render_html, render_markdown

def run_flow(flow, shared, out_dir, dump_state):
    """Run `flow` against `shared`, keeping its partial progress on failure
    (see keeping_results)."""
    keeping_results(lambda: flow.run(shared), shared, out_dir, dump_state)


def keeping_results(step, shared, out_dir, dump_state):
    """Call `step()`. On an unhandled exception, or Ctrl-C, call
    `dump_state(shared, out_dir)` to write whatever results `shared` holds,
    say where they landed on stderr beside the traceback, and re-raise (an
    interrupt keeps its exit status). A dump that fails is
    reported the same way and the step's own error is still the one that
    propagates; a dump that returns None had nothing to write and says
    nothing. Covers the report write as well as the flow: once the flow has
    returned, `shared` holds every paid result, and a renderer error loses
    them just as a failed node would (coderay-5wu.4)."""
    try:
        step()
    except (Exception, SystemExit, KeyboardInterrupt) as why:
        what = "Run interrupted" if isinstance(why, KeyboardInterrupt) else "Run failed"
        try:
            state_path = dump_state(shared, out_dir)
        except Exception as e:  # the dump's own error is printed here; the step's is what propagates
            print(f"\n{what}, and the partial run state could not be written to {out_dir}: {type(e).__name__}: {e}",
                  file=sys.stderr)
        else:
            if state_path:
                print(f"\n{what}. Wrote partial run state to {state_path}", file=sys.stderr)
        raise

def write_run_state(shared, out_dir, skip=frozenset()):
    """Write `shared`, minus the keys in `skip`, to run_state.json in out_dir
    and return the path, or None when nothing is left to write.

    Every LLM result a pipeline has produced so far lives in `shared`, so this
    is what the user gets back when a later node fails (coderay-q2r.49). The
    caller passes the pipeline's input keys as `skip`: the source bundle is
    free to regenerate and can be most of a megabyte. Values JSON cannot
    represent are written as their str(). Serialised in full before the file
    is opened, so a serialisation error cannot leave a truncated file."""
    results = {k: v for k, v in shared.items() if k not in skip}
    if not results:
        return None
    text = json.dumps(results, indent=2, default=str)
    path = os.path.join(out_dir, "run_state.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_state_writer(out_dir, shared, input_keys):
    """Remove a run_state.json left by an earlier failed run in out_dir (the
    default output directory is the same run to run) and return the dump
    callable keeping_results takes: `shared` minus the keys present before the
    flow ran and the analysis's INPUT_KEYS, which regenerate without an LLM
    call and can be most of a megabyte."""
    stale = os.path.join(out_dir, "run_state.json")
    if os.path.exists(stale):
        os.remove(stale)
    inputs = frozenset(shared) | input_keys
    return lambda s, o: write_run_state(s, o, skip=inputs)


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
    may write extra files into it during the run. If the flow or the report
    write raises, whatever the flow added to `shared` is written to
    run_state.json there and the exception propagates (run_state_writer)."""
    out_dir = args.out or default_output_dir(args.repo_path, analysis.NAME)
    os.makedirs(out_dir, exist_ok=True)

    name = repo_name_of(args.repo_path)
    shared = analysis.init_shared(args)
    dump = run_state_writer(out_dir, shared, getattr(analysis, "INPUT_KEYS", frozenset()))

    def run_and_report():
        with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
            analysis.build_flow().run(shared)
        write_report(analysis, name, shared, out_dir)

    keeping_results(run_and_report, shared, out_dir, dump)

    print(f"\nWrote {analysis.NAME} to {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser")
    return out_dir
