import argparse

import pytest

from crawl.core.text import codebase_budget_argument


def _parse(argv, monkeypatch, default=650_000, env=None):
    monkeypatch.delenv("CODEBASE_BUDGET", raising=False)
    if env is not None:
        monkeypatch.setenv("CODEBASE_BUDGET", env)
    parser = argparse.ArgumentParser(prog="crawl x")
    parser.add_argument("--codebase-budget", **codebase_budget_argument(default))
    return parser.parse_args(argv)


def test_defaults_to_the_given_default(monkeypatch):
    assert _parse([], monkeypatch, default=500_000).codebase_budget == 500_000


def test_env_var_applies_when_the_flag_is_absent(monkeypatch):
    assert _parse([], monkeypatch, env="2000000").codebase_budget == 2_000_000


def test_an_empty_env_var_means_unset(monkeypatch):
    assert _parse([], monkeypatch, default=900_000, env="").codebase_budget == 900_000


def test_flag_wins_over_the_env_var(monkeypatch):
    args = _parse(["--codebase-budget", "300"], monkeypatch, env="2000000")
    assert args.codebase_budget == 300


@pytest.mark.parametrize("bad", ["abc", "1.5", "0", "-7"])
def test_rejects_a_bad_flag_value_at_parse_time(monkeypatch, capsys, bad):
    with pytest.raises(SystemExit) as e:
        _parse(["--codebase-budget", bad], monkeypatch)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "--codebase-budget" in err and "CODEBASE_BUDGET" in err and repr(bad) in err


def test_rejects_a_bad_env_value_at_parse_time(monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _parse([], monkeypatch, env="lots")
    assert e.value.code == 2
    assert "CODEBASE_BUDGET" in capsys.readouterr().err
