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

def test_add_arguments_adds_no_flags_of_its_own():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    before = {a.dest for a in parser._actions}
    backend.add_arguments(parser)
    assert {a.dest for a in parser._actions} == before

def test_init_shared_carries_the_repo_path():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    assert backend.init_shared(args) == {"repo_path": "/tmp/toy_repo"}

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
