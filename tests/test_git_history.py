import argparse
import os

import pytest

from crack.analyses import ANALYSES, git_history


def test_git_history_is_registered_under_its_hyphenated_name():
    """The module is git_history; the subcommand is `crack git-history`."""
    assert ANALYSES["git-history"] is git_history
    assert git_history.NAME == "git-history"


def test_git_history_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(git_history, attr), attr


def test_git_history_brings_its_own_renderer_instead_of_the_card_contract():
    """crack.core.render defers to a custom render_html when one exists, so this
    analysis needs no SECTIONS or THEME -- and must not grow them by accident."""
    assert callable(git_history.render_html)
    assert callable(git_history.render_markdown)
    assert not hasattr(git_history, "SECTIONS")
    assert not hasattr(git_history, "THEME")


def test_the_shared_renderer_routes_to_the_analysis_own_renderer():
    """The delegation is what lets regen_golden.py reach a bespoke analysis."""
    from crack.core import render
    called = {}

    class Fake:
        NAME = "fake"
        @staticmethod
        def render_html(name, shared):
            called["html"] = name
            return "<html>"

    assert render.render_html(Fake, "toy_repo", {}) == "<html>"
    assert called["html"] == "toy_repo"


def test_git_history_does_not_raise_the_output_token_ceiling():
    assert git_history.ENV_DEFAULTS == {}


def test_add_arguments_adds_the_graveyard_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    git_history.add_arguments(parser)
    args = parser.parse_args(["/tmp/repo", "--max-graves", "3", "--grave-min-files", "20"])
    assert args.max_graves == 3
    assert args.grave_min_files == 20


def test_add_arguments_defaults_match_what_the_nodes_expect():
    """The nodes read these out of shared with their own fallbacks; a drift
    between the two would silently change behaviour depending on the caller."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    git_history.add_arguments(parser)
    args = parser.parse_args(["/tmp/repo"])
    assert args.max_graves == 6
    assert args.grave_min_files == 8


def test_init_shared_carries_the_repo_path_and_the_flags():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None,
                              max_graves=3, grave_min_files=20)
    assert git_history.init_shared(args) == {
        "repo_path": "/tmp/toy_repo", "max_graves": 3, "grave_min_files": 20}


def test_init_shared_tolerates_an_args_without_the_flags():
    """run_analysis is shared, and other callers build args without them."""
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    shared = git_history.init_shared(args)
    assert shared["max_graves"] == 6
    assert shared["grave_min_files"] == 8


def test_build_flow_starts_at_fetch_history():
    from crack.analyses.git_history.nodes import FetchHistory
    assert isinstance(git_history.build_flow().start_node, FetchHistory)


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        git_history.run(argparse.Namespace(repo_path=str(f), out=None))


def test_overview_spec_names_the_three_sections_and_counts_the_history():
    spec = git_history.overview_spec({
        "repo_path": "/tmp/toy_repo",
        "eras": [{"name": "Early"}, {"name": "Growth"}],
        "graves": [{}, {}, {}],
        "commits": [{}] * 4821})
    assert spec["name"] == "toy_repo"
    assert [t for t, _ in spec["sections"]] == ["The eras", "Cast & mood", "The graveyard"]
    assert "Early, Growth" in spec["facts"]
    assert "3 killed features" in spec["facts"]
    assert "4,821 commits" in spec["facts"]


def test_overview_spec_name_matches_the_name_the_page_is_rendered_with(tmp_path, monkeypatch):
    from crack.core.runner import repo_name_of
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    spec = git_history.overview_spec({"repo_path": ".", "eras": [], "graves": [], "commits": []})
    assert spec["name"] == repo_name_of(".") == "toy_repo"
    assert spec["name"] != os.path.basename(".")
