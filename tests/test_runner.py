import os

import pytest

from crack.core.render import Section, Theme
from crack.core.runner import run_analysis, run_flow


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
    assert (out / "index.html").read_text().startswith("<!doctype html>")
    assert (out / "index.md").read_text().startswith("# ")


def test_run_analysis_defaults_the_output_dir_to_cwd_output(tmp_path, monkeypatch):
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    out = run_analysis(_fake_analysis(), _Args(str(repo)))
    assert out == os.path.join(str(tmp_path), "output", "toy_repo-demo")
    assert os.path.isfile(os.path.join(out, "index.html"))


def test_run_analysis_applies_env_defaults_during_the_flow(tmp_path):
    record = {}
    analysis = _fake_analysis({"LLM_MAX_OUTPUT_TOKENS": "32768"}, record)
    run_analysis(analysis, _Args(str(tmp_path), out=str(tmp_path / "o")))
    assert record["max_tokens"] == "32768"
    assert "LLM_MAX_OUTPUT_TOKENS" not in os.environ


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
