import argparse
import os

import pytest

from crawl.analyses import ANALYSES
from crawl.analyses import backend

def test_backend_is_registered():
    assert ANALYSES["backend"] is backend
    assert backend.NAME == "backend"

def test_backend_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(backend, attr), attr

def test_backend_declares_the_card_family_contract():
    assert len(backend.SECTIONS) == 3
    assert [s.key for s in backend.SECTIONS] == ["pipeline_md", "layercode_md", "trace_md"]
    assert [s.number for s in backend.SECTIONS] == ["01", "02", "03"]
    assert backend.THEME.title_suffix == "backend"

def test_backend_raises_more_output_tokens():
    assert backend.ENV_DEFAULTS == {"LLM_MAX_OUTPUT_TOKENS": "32768"}

def test_add_arguments_adds_only_codebase_budget():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    before = {a.dest for a in parser._actions}
    backend.add_arguments(parser)
    assert {a.dest for a in parser._actions} - before == {"codebase_budget"}

def test_init_shared_carries_the_repo_path_and_budget():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None, codebase_budget=650_000)
    assert backend.init_shared(args) == {"repo_path": "/tmp/toy_repo", "codebase_budget": 650_000}


# coderay-mlb: the codebase budget is settable from the command line and the
# environment, like tour's.
def _parse(argv, monkeypatch, env=None):
    monkeypatch.delenv("CODEBASE_BUDGET", raising=False)
    if env is not None:
        monkeypatch.setenv("CODEBASE_BUDGET", env)
    parser = argparse.ArgumentParser(prog="crawl backend")
    parser.add_argument("repo_path")
    backend.add_arguments(parser)
    return parser.parse_args(["repo", *argv])


def test_codebase_budget_defaults_to_the_backend_constant(monkeypatch):
    from crawl.analyses.backend.backend_crawl import DEFAULT_MAX_CHARS
    args = _parse([], monkeypatch)
    assert args.codebase_budget == DEFAULT_MAX_CHARS
    assert backend.init_shared(args)["codebase_budget"] == DEFAULT_MAX_CHARS


@pytest.mark.parametrize("bad", ["abc", "1.5", "0", "-7"])
def test_codebase_budget_rejects_a_bad_value_at_parse_time(monkeypatch, capsys, bad):
    with pytest.raises(SystemExit) as e:
        _parse(["--codebase-budget", bad], monkeypatch)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "--codebase-budget" in err and "CODEBASE_BUDGET" in err and repr(bad) in err


def test_codebase_budget_rejects_a_bad_env_value_at_parse_time(monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _parse([], monkeypatch, env="lots")
    assert e.value.code == 2
    assert "CODEBASE_BUDGET" in capsys.readouterr().err


def test_build_bundle_prep_reads_the_budget_from_shared():
    from crawl.analyses.backend.backend_crawl import DEFAULT_MAX_CHARS
    from crawl.analyses.backend.nodes import BuildBundle
    node = BuildBundle()
    assert node.prep({"repo_path": "/tmp/x", "codebase_budget": 4242}) == ("/tmp/x", 4242)
    # A shared dict built without going through init_shared (as unit tests do)
    # still gets the crawl module's own default.
    assert node.prep({"repo_path": "/tmp/x"}) == ("/tmp/x", DEFAULT_MAX_CHARS)


def test_build_bundle_exec_hands_the_budget_to_build_bundle(monkeypatch):
    import crawl.analyses.backend.nodes as backend_nodes
    from crawl.analyses.backend.nodes import BuildBundle
    seen = {}

    def fake_build_bundle(repo, max_chars):
        seen["repo"], seen["max_chars"] = repo, max_chars
        return "bundle", {"counts": {}}

    monkeypatch.setattr(backend_nodes.bc, "build_bundle", fake_build_bundle)
    BuildBundle().exec(("/tmp/x", 4242))
    assert seen == {"repo": "/tmp/x", "max_chars": 4242}

def test_build_flow_starts_at_build_bundle():
    from crawl.analyses.backend.nodes import BuildBundle
    assert isinstance(backend.build_flow().start_node, BuildBundle)

def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        backend.run(argparse.Namespace(repo_path=str(f), out=None))

def test_overview_spec_names_the_three_sections():
    spec = backend.overview_spec({"repo_path": "/tmp/toy_repo", "layer_counts": {"route": 4}})
    assert spec["name"] == "toy_repo"
    assert [t for t, _ in spec["sections"]] == ["The pipeline", "The code", "The trace"]
    assert "route 4" in spec["facts"]


def test_overview_spec_name_matches_the_name_the_page_is_rendered_with(tmp_path, monkeypatch):
    """The overview prompt and the page title must name the same repo.

    run_analysis hands the renderer repo_name_of(args.repo_path) as the page
    title. If overview_spec computed the name differently, the LLM-written copy
    would name a different repo than the heading above it. "." is the case that
    exposes a divergence.
    """
    from crawl.core.runner import repo_name_of

    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    spec = backend.overview_spec({"repo_path": ".", "layer_counts": {}})
    assert spec["name"] == repo_name_of(".") == "toy_repo"
    # "." is the shape that separates the two implementations: a naive
    # os.path.basename(repo_path) returns "." here, not the directory name.
    assert spec["name"] != os.path.basename(".")
