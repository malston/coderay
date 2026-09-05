"""Runs a pipeline flow against a shared state dict, common to any analysis."""
import json
import os
import sys
from datetime import datetime, timezone

from .call_llm import get_usage
from .env import env_defaults
from .files import write_text_atomic
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
    return _write_json(os.path.join(out_dir, "run_state.json"), results)


def _write_json(path, obj):
    """Serialise in full before any file is touched, so a serialisation error
    cannot leave a truncated or empty file passing for a record; the write
    itself is atomic for the same reason."""
    return write_text_atomic(path, json.dumps(obj, indent=2, default=str))


def run_state_writer(out_dir, shared, input_keys):
    """Remove the run_state.json and manifest.json an earlier run left in
    out_dir (the default output directory is the same run to run, and either
    would describe the wrong run beside this one's output) and return the dump
    callable keeping_results takes: `shared` minus the keys present before the
    flow ran and the analysis's INPUT_KEYS, which regenerate without an LLM
    call and can be most of a megabyte."""
    for stale in ("run_state.json", "manifest.json"):
        if os.path.exists(os.path.join(out_dir, stale)):
            os.remove(os.path.join(out_dir, stale))
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
    write_text_atomic(os.path.join(out_dir, "index.md"), render_markdown(analysis, name, shared))
    write_text_atomic(os.path.join(out_dir, "index.html"), render_html(analysis, name, shared))
    return out_dir


def write_manifest(analysis_name, repo_name, described, out_dir, usage):
    """Write manifest.json beside the report: which repo content the prompts
    carried, as the analysis's own sent(shared) describes it (`described`:
    file paths for most, commit hashes for git-history); `llm`, the provider
    and model pairs this run called live (`usage` is its slice of the usage
    log); `cached_calls`, how many prompts the local response cache answered,
    which never left the machine; and when. Repo content leaves the machine on
    a live run, and this is the record of what did (coderay-3eu). Returns the
    path."""
    live = {(u["provider"], u["model"]) for u in usage if not u["cached"]}
    manifest = {
        "analysis": analysis_name,
        "repo": repo_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm": [{"provider": p, "model": m} for p, m in sorted(live)],
        "cached_calls": sum(1 for u in usage if u["cached"]),
        **described,
    }
    return _write_json(os.path.join(out_dir, "manifest.json"), manifest)


def run_analysis(analysis, args):
    """Run one analysis and write its index.md, index.html and manifest.json.
    Returns out_dir.

    The output directory is created before the flow runs, because an analysis
    may write extra files into it during the run. If the flow or the report
    write raises, whatever the flow added to `shared` is written to
    run_state.json there and the exception propagates (run_state_writer)."""
    out_dir = args.out or default_output_dir(args.repo_path, analysis.NAME)
    os.makedirs(out_dir, exist_ok=True)

    name = repo_name_of(args.repo_path)
    shared = analysis.init_shared(args)
    dump = run_state_writer(out_dir, shared, getattr(analysis, "INPUT_KEYS", frozenset()))
    first_call = len(get_usage())  # the manifest records this run's calls, not an embedder's

    def run_and_report():
        with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
            analysis.build_flow().run(shared)
        write_report(analysis, name, shared, out_dir)
        write_manifest(analysis.NAME, name, analysis.sent(shared), out_dir, get_usage()[first_call:])

    keeping_results(run_and_report, shared, out_dir, dump)

    print(f"\nWrote {analysis.NAME} to {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser")
    return out_dir
