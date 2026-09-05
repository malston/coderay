import json
import os
import subprocess
import sys
import textwrap

import pytest

from crawl.core.render import Section, Theme, render_html, render_markdown
from crawl.core.runner import keeping_results, run_analysis, run_flow


def test_run_flow_dumps_state_and_reraises_on_failure():
    class FailingFlow:
        def run(self, shared):
            raise RuntimeError("boom")

    dumped = {}

    def dump_state(shared, out_dir):
        dumped["shared"], dumped["out_dir"] = shared, out_dir
        return "/tmp/run_state.json"

    with pytest.raises(RuntimeError):
        run_flow(FailingFlow(), {"x": 1}, "/tmp", dump_state)

    assert dumped == {"shared": {"x": 1}, "out_dir": "/tmp"}


def test_run_flow_does_not_call_dump_state_on_success():
    class OkFlow:
        def run(self, shared):
            pass

    calls = []
    run_flow(OkFlow(), {}, "/tmp", lambda *a: calls.append(a))
    assert calls == []


class _Args:
    def __init__(self, repo_path, out=None):
        self.repo_path = repo_path
        self.out = out


def _fake_analysis(env_defaults_dict=None, record=None):
    class Flow:
        def run(self, shared):
            shared["body_md"] = "### A\ntext"
            if record is not None:
                record["max_tokens"] = os.environ.get("LLM_MAX_OUTPUT_TOKENS")

    class Analysis:
        NAME = "demo"
        SECTIONS = [Section("01", "Only", "note", "rail", 400, "body_md")]
        THEME = Theme(
            title_suffix="demo", eyebrow="Demo", accent="#000", accent_soft="#eee",
            hero_from="#111", hero_to="#222", eyebrow_color="#333", eyebrow_bar="#444",
            sub_color="#555", card_top_from="#666",
            subtitle=lambda sh: "sub", footer=lambda sh: "foot",
            md_preamble=lambda sh: "")
        init_shared = staticmethod(lambda args: {"repo_path": args.repo_path})
        build_flow = staticmethod(Flow)
        sent = staticmethod(lambda shared: {"files": []})

    Analysis.INPUT_KEYS = frozenset()
    if env_defaults_dict:
        Analysis.ENV_DEFAULTS = env_defaults_dict
    return Analysis


def test_run_analysis_writes_both_index_files(tmp_path):
    out = tmp_path / "out"
    run_analysis(_fake_analysis(), _Args(str(tmp_path), out=str(out)))
    assert (out / "index.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert (out / "index.md").read_text(encoding="utf-8").startswith("# ")


def test_run_analysis_defaults_the_output_dir_to_cwd_output(tmp_path, monkeypatch):
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    out = run_analysis(_fake_analysis(), _Args(str(repo)))
    assert out == os.path.join(str(tmp_path), "output", "toy_repo-demo")
    assert os.path.isfile(os.path.join(out, "index.html"))


def test_run_analysis_applies_env_defaults_during_the_flow(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    before = os.environ.get("LLM_MAX_OUTPUT_TOKENS")
    record = {}
    analysis = _fake_analysis({"LLM_MAX_OUTPUT_TOKENS": "32768"}, record)
    run_analysis(analysis, _Args(str(tmp_path), out=str(tmp_path / "o")))
    assert record["max_tokens"] == "32768"
    assert os.environ.get("LLM_MAX_OUTPUT_TOKENS") == before


def test_run_analysis_creates_the_output_dir_before_the_flow_runs(tmp_path):
    out = tmp_path / "o"
    seen = {}

    class Flow:
        def run(self, shared):
            seen["existed"] = out.is_dir()
            shared["body_md"] = "### A\nt"

    analysis = _fake_analysis()
    analysis.build_flow = staticmethod(Flow)
    run_analysis(analysis, _Args(str(tmp_path), out=str(out)))
    assert seen["existed"] is True


def test_run_analysis_writes_utf8_output_under_the_c_locale(tmp_path):
    """A monkeypatched locale does not reproduce this: index.md/index.html
    must open for writing with an explicit encoding, or a real C-locale
    process (the container/CI default) raises UnicodeEncodeError after every
    LLM call in the run has already been paid for."""
    out = tmp_path / "out"
    script = tmp_path / "run_it.py"
    script.write_text(textwrap.dedent(f"""
        from crawl.core.render import Section, Theme
        from crawl.core.runner import run_analysis

        class Flow:
            def run(self, shared):
                shared["body_md"] = "### A\\ntext with an em dash \\u2014 end"

        class Analysis:
            NAME = "demo"
            SECTIONS = [Section("01", "Only", "note", "rail", 400, "body_md")]
            THEME = Theme(
                title_suffix="demo", eyebrow="Demo", accent="#000", accent_soft="#eee",
                hero_from="#111", hero_to="#222", eyebrow_color="#333", eyebrow_bar="#444",
                sub_color="#555", card_top_from="#666",
                subtitle=lambda sh: "sub", footer=lambda sh: "foot",
                md_preamble=lambda sh: "")
            init_shared = staticmethod(lambda args: {{"repo_path": args.repo_path}})
            build_flow = staticmethod(Flow)
            sent = staticmethod(lambda shared: {{"files": []}})

        class Args:
            repo_path = {str(tmp_path)!r}
            out = {str(out)!r}

        run_analysis(Analysis, Args())
        """), encoding="utf-8")
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0")
    result = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "—" in (out / "index.md").read_text(encoding="utf-8")


def test_run_flow_dumps_state_when_a_node_exits_deliberately():
    """coderay-q2r.46: a truncated chapter exits the run via SystemExit so
    the node does not retry it; the partial state must still be written."""
    class ExitingFlow:
        def run(self, shared):
            raise SystemExit("cap too low")

    dumped = {}
    with pytest.raises(SystemExit):
        run_flow(ExitingFlow(), {"x": 1}, "/tmp", lambda s, o: dumped.setdefault("s", s) and "/tmp/x")
    assert dumped == {"s": {"x": 1}}


def test_write_report_is_the_one_place_index_files_are_written(tmp_path):
    """run_analysis and scripts/regen_golden.py both write index.md and
    index.html through this helper, so a fixture and a real run cannot drift."""
    from crawl.core.runner import write_report
    analysis = _fake_analysis()
    out = write_report(analysis, "toy", {"x": 1}, tmp_path / "out")
    assert out == tmp_path / "out"
    assert (tmp_path / "out" / "index.md").read_text(encoding="utf-8") == render_markdown(analysis, "toy", {"x": 1})
    assert (tmp_path / "out" / "index.html").read_text(encoding="utf-8") == render_html(analysis, "toy", {"x": 1})


def _failing_analysis(fail=RuntimeError("boom"), produce=True):
    """The first node stores the bundle, as every real analysis does, so the
    skip set must come from the analysis's declared INPUT_KEYS, not from what
    init_shared happened to set."""
    class FailingFlow:
        def run(self, shared):
            shared["codebase"] = "x" * 1000
            if produce:
                shared["pipeline_md"] = "paid prose"
                shared["odd"] = {"a-set"}
            raise fail

    analysis = _fake_analysis()
    analysis.INPUT_KEYS = frozenset({"codebase"})
    analysis.build_flow = staticmethod(FailingFlow)
    return analysis


def test_run_analysis_writes_partial_state_when_a_later_node_fails(tmp_path, capsys):
    """coderay-q2r.49. Every earlier LLM result is in `shared` when a late node
    exhausts its retries; the user paid for it and must get it back. The
    pipeline's inputs are not results: the source bundle is left out, since it
    is free to regenerate and can be most of a megabyte."""
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        run_analysis(_failing_analysis(), _Args(str(tmp_path), out=str(out)))
    state = json.loads((out / "run_state.json").read_text(encoding="utf-8"))
    assert state["pipeline_md"] == "paid prose"
    assert "a-set" in state["odd"]
    assert "codebase" not in state and "repo_path" not in state
    assert not (out / "index.html").exists() and not (out / "index.md").exists()
    assert f"Wrote partial run state to {out / 'run_state.json'}" in capsys.readouterr().err


def test_a_failing_dump_keeps_the_pipeline_error_and_leaves_no_half_written_file(tmp_path, monkeypatch, capsys):
    """If the state file cannot be written, the traceback the user reads must
    still end in the pipeline's own error, the notice must say the state was
    lost, and no truncated run_state.json may pass for partial state."""
    import crawl.core.runner as runner
    out = tmp_path / "out"
    monkeypatch.setattr(runner.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("unserialisable")))
    with pytest.raises(RuntimeError, match="boom"):
        run_analysis(_failing_analysis(), _Args(str(tmp_path), out=str(out)))
    assert not (out / "run_state.json").exists()
    assert "partial run state could not be written" in capsys.readouterr().err


def test_a_later_successful_run_removes_the_stale_state_file(tmp_path):
    """The default output dir is deterministic, so a state file from an earlier
    failure would sit beside a fresh index.html and read as a second failure."""
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        run_analysis(_failing_analysis(), _Args(str(tmp_path), out=str(out)))
    assert (out / "run_state.json").exists()
    run_analysis(_fake_analysis(), _Args(str(tmp_path), out=str(out)))
    assert (out / "index.html").exists() and not (out / "run_state.json").exists()


def test_a_failure_before_any_result_writes_no_state_file(tmp_path, capsys):
    """Every analysis has a pre-flight guard that raises before the first LLM
    call. With nothing produced there is nothing to keep, so no run_state.json
    and no partial-state notice above the real diagnostic."""
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        run_analysis(_failing_analysis(produce=False), _Args(str(tmp_path), out=str(out)))
    assert not (out / "run_state.json").exists()
    assert "partial run state" not in capsys.readouterr().err


def test_run_analysis_writes_partial_state_when_the_report_write_fails(tmp_path, monkeypatch, capsys):
    """coderay-5wu.4. After the flow succeeds `shared` holds every paid result;
    a renderer bug or a full disk while writing index.html must not lose them
    one step after the flow's own failure would have kept them."""
    import crawl.core.runner as runner
    monkeypatch.setattr(runner, "render_html", lambda *a: (_ for _ in ()).throw(KeyError("evidence")))
    out = tmp_path / "out"
    with pytest.raises(KeyError, match="evidence"):
        run_analysis(_fake_analysis(), _Args(str(tmp_path), out=str(out)))
    state = json.loads((out / "run_state.json").read_text(encoding="utf-8"))
    assert state == {"body_md": "### A\ntext"}
    assert f"Run failed. Wrote partial run state to {out / 'run_state.json'}" in capsys.readouterr().err


def test_an_interrupt_keeps_the_results_and_still_propagates(capsys):
    """coderay-5wu.2 (Mark's call): Ctrl-C on chapter 9 of 10 has paid for
    eight chapters. Dump them, say so, and re-raise so the interrupt exits
    the process the way an interrupt does."""
    def step():
        raise KeyboardInterrupt

    dumped = {}

    def dump_state(shared, out_dir):
        dumped["shared"], dumped["out_dir"] = shared, out_dir
        return "/tmp/x"

    with pytest.raises(KeyboardInterrupt):
        keeping_results(step, {}, "/tmp", dump_state)
    assert dumped == {"shared": {}, "out_dir": "/tmp"}
    assert "Run interrupted. Wrote partial run state to /tmp/x" in capsys.readouterr().err


def test_an_interrupt_whose_dump_fails_still_propagates_and_says_the_state_was_lost(tmp_path, monkeypatch, capsys):
    import crawl.core.runner as runner
    out = tmp_path / "out"
    monkeypatch.setattr(runner.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("unserialisable")))
    with pytest.raises(KeyboardInterrupt):
        run_analysis(_failing_analysis(fail=KeyboardInterrupt()), _Args(str(tmp_path), out=str(out)))
    assert not (out / "run_state.json").exists()
    assert "Run interrupted, and the partial run state could not be written" in capsys.readouterr().err


# coderay-3eu: a successful run records what left the machine.
def test_run_analysis_writes_a_manifest_of_what_was_sent(tmp_path):
    analysis = _fake_analysis()
    analysis.sent = staticmethod(lambda shared: {"files": ["a.py", "b.py"]})
    out = tmp_path / "out"
    run_analysis(analysis, _Args(str(tmp_path), out=str(out)))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis"] == "demo" and manifest["repo"] == tmp_path.name
    assert manifest["files"] == ["a.py", "b.py"]
    assert manifest["generated_at"].endswith("+00:00")
    assert manifest["llm"] == []  # no call_llm ran in this fake


def test_a_failed_run_writes_no_manifest(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        run_analysis(_failing_analysis(), _Args(str(tmp_path), out=str(out)))
    assert not (out / "manifest.json").exists()


def test_the_manifest_lists_this_runs_provider_and_model_pairs_once_each(tmp_path):
    import importlib
    llm = importlib.import_module("crawl.core.call_llm")  # crawl.core re-exports a function of that name
    llm._record_usage("gemini", "stale-from-an-earlier-run", 1, 1, 0, 0, 0.0, False)

    class Flow:
        def run(self, shared):
            shared["body_md"] = "### A\ntext"
            llm._record_usage("openai", "n", 1, 1, 0, 0, 0.0, False)
            llm._record_usage("anthropic", "m", 1, 1, 0, 0, 0.0, False)
            llm._record_usage("anthropic", "m", 1, 1, 0, 0, 0.0, True)

    analysis = _fake_analysis()
    analysis.build_flow = staticmethod(Flow)
    out = tmp_path / "out"
    run_analysis(analysis, _Args(str(tmp_path), out=str(out)))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["llm"] == [{"provider": "anthropic", "model": "m"}, {"provider": "openai", "model": "n"}]


def test_a_rerun_that_fails_leaves_no_earlier_manifest_behind(tmp_path):
    """The output directory is the same run to run; a manifest from an earlier
    successful run beside a fresh run_state.json would describe the wrong run."""
    out = tmp_path / "out"
    run_analysis(_fake_analysis(), _Args(str(tmp_path), out=str(out)))
    assert (out / "manifest.json").exists()
    with pytest.raises(RuntimeError):
        run_analysis(_failing_analysis(), _Args(str(tmp_path), out=str(out)))
    assert not (out / "manifest.json").exists()


def test_the_manifest_separates_live_calls_from_cache_hits(tmp_path):
    """A rerun served from the LLM disk cache sends nothing; the manifest must
    not read like a live run."""
    import importlib
    llm = importlib.import_module("crawl.core.call_llm")

    class Flow:
        def run(self, shared):
            shared["body_md"] = "### A\ntext"
            llm._record_usage("anthropic", "m", 0, 0, 0, 0, 0.0, True)
            llm._record_usage("anthropic", "m", 0, 0, 0, 0, 0.0, True)

    analysis = _fake_analysis()
    analysis.build_flow = staticmethod(Flow)
    out = tmp_path / "out"
    run_analysis(analysis, _Args(str(tmp_path), out=str(out)))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["llm"] == [] and manifest["cached_calls"] == 2
