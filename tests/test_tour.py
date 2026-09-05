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
