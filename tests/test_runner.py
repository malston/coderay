import os
import subprocess
import sys
import textwrap

import pytest

from crawl.core.render import Section, Theme
from crawl.core.runner import run_analysis, run_flow


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
