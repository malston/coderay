import argparse

import pytest

from crawl.analyses.tour import run


def test_run_exits_with_message_when_repo_path_is_not_a_directory(tmp_path):
    args = argparse.Namespace(repo_path=str(tmp_path / "missing"), out=None,
                               instructions="beginner-tutorial", dry_run=False)
    with pytest.raises(SystemExit, match="is not a directory"):
        run(args)


# coderay-5wu.15: the codebase budget is settable from the command line and the
# environment. Flag over env over the constant.
def _parse(argv, monkeypatch, env=None):
    from crawl.analyses.tour import add_arguments
    monkeypatch.delenv("CODEBASE_BUDGET", raising=False)
    if env is not None:
        monkeypatch.setenv("CODEBASE_BUDGET", env)
    parser = argparse.ArgumentParser(prog="crawl tour")
    parser.add_argument("repo_path")
    add_arguments(parser)
    return parser.parse_args(["repo", *argv])


def test_codebase_budget_defaults_to_the_constant(monkeypatch):
    from crawl.analyses.tour import init_shared
    from crawl.analyses.tour.nodes import CODEBASE_BUDGET
    args = _parse([], monkeypatch)
    assert args.codebase_budget == CODEBASE_BUDGET
    assert init_shared(args)["codebase_budget"] == CODEBASE_BUDGET


def test_an_empty_codebase_budget_env_var_means_unset(monkeypatch):
    """.env.example ships `CODEBASE_BUDGET=`; sourcing it exports the empty string,
    which the rest of the project reads as unset."""
    from crawl.analyses.tour.nodes import CODEBASE_BUDGET
    assert _parse([], monkeypatch, env="").codebase_budget == CODEBASE_BUDGET


def test_codebase_budget_env_var_applies_when_the_flag_is_absent(monkeypatch):
    assert _parse([], monkeypatch, env="2000000").codebase_budget == 2_000_000


def test_codebase_budget_flag_wins_over_the_env_var(monkeypatch):
    from crawl.analyses.tour import init_shared
    args = _parse(["--codebase-budget", "300"], monkeypatch, env="2000000")
    assert args.codebase_budget == 300
    assert init_shared(args)["codebase_budget"] == 300


def test_run_hands_the_parsed_budget_to_the_flow(tmp_path, monkeypatch):
    """The dry run reporting a budget is not the same as the real run using it."""
    import crawl.analyses.tour as tour

    class Stop(Exception):
        pass

    seen = {}

    def fake_run_flow(flow, shared, out, dump):
        seen.update(shared)
        raise Stop

    monkeypatch.setattr(tour, "resolve_provider_and_model", lambda: ("anthropic", "m"))
    monkeypatch.setattr(tour, "ensure_priced", lambda p, m: None)
    monkeypatch.setattr(tour, "run_flow", fake_run_flow)
    args = argparse.Namespace(repo_path=str(tmp_path), out=str(tmp_path / "o"),
                              instructions="beginner-tutorial", dry_run=False, codebase_budget=4242)
    with pytest.raises(Stop):
        run(args)
    assert seen["codebase_budget"] == 4242


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


def test_run_keeps_the_run_state_when_a_tour_file_write_fails(tmp_path, monkeypatch, capsys):
    """coderay-5wu.4. After the flow returns, shared holds every paid result;
    a failed chapter or index write must leave run_state.json behind as a
    failed node would."""
    import json
    import crawl.analyses.tour as tour

    def fake_run_flow(flow, shared, out, dump):
        shared.update(selected_files=["a.py"], selection_reasoning="", abstractions=[{"name": "Engine"}],
                      relationships=[], order=[0], chapters=[{"name": "Engine"}], summary="s")

    monkeypatch.setattr(tour, "resolve_provider_and_model", lambda: ("anthropic", "m"))
    monkeypatch.setattr(tour, "ensure_priced", lambda p, m: None)
    monkeypatch.setattr(tour, "run_flow", fake_run_flow)
    monkeypatch.setattr(tour, "write_chapter_files", lambda *a: None)
    monkeypatch.setattr(tour, "write_index_md", lambda *a: None)
    monkeypatch.setattr(tour, "write_index_html", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    out = tmp_path / "o"
    args = argparse.Namespace(repo_path=str(tmp_path), out=str(out), instructions="beginner-tutorial",
                              dry_run=False, codebase_budget=1_000_000)
    with pytest.raises(OSError, match="disk full"):
        run(args)
    state = json.loads((out / "run_state.json").read_text(encoding="utf-8"))
    assert state["chapters"] == [{"name": "Engine"}] and state["summary"] == "s"
    assert "codebase" not in state and "repo_path" not in state and "codebase_budget" not in state
    assert f"Wrote partial run state to {out / 'run_state.json'}" in capsys.readouterr().err


def test_run_removes_a_stale_state_file_and_writes_none_on_success(tmp_path, monkeypatch):
    """The tour's output directory is the same run to run, so a state file from
    an earlier failure would sit beside fresh chapters and read as a failure."""
    import crawl.analyses.tour as tour

    def fake_run_flow(flow, shared, out, dump):
        shared.update(selected_files=[], selection_reasoning="", abstractions=[], relationships=[],
                      order=[], chapters=[], summary="s")

    monkeypatch.setattr(tour, "resolve_provider_and_model", lambda: ("anthropic", "m"))
    monkeypatch.setattr(tour, "ensure_priced", lambda p, m: None)
    monkeypatch.setattr(tour, "run_flow", fake_run_flow)
    for w in ("write_chapter_files", "write_index_md", "write_index_html"):
        monkeypatch.setattr(tour, w, lambda *a: None)
    out = tmp_path / "o"
    out.mkdir()
    (out / "run_state.json").write_text("{}", encoding="utf-8")
    args = argparse.Namespace(repo_path=str(tmp_path), out=str(out), instructions="beginner-tutorial",
                              dry_run=False, codebase_budget=1_000_000)
    run(args)
    assert not (out / "run_state.json").exists()
