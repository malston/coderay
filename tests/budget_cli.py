"""Shared test support for --codebase-budget/CODEBASE_BUDGET across analyses.

Every analysis wires the same crawl.core.text.codebase_budget_argument()
helper through its own add_arguments; these helpers exercise that wiring
without re-deriving the argparse setup and assertions in each test file.
"""
import argparse

import pytest

BAD_BUDGET_VALUES = ["abc", "1.5", "0", "-7"]


def parse_with_budget(add_arguments, prog, argv, monkeypatch, env=None):
    """Parse `argv` through an analysis's add_arguments with repo_path and
    --codebase-budget wired, isolating CODEBASE_BUDGET first."""
    monkeypatch.delenv("CODEBASE_BUDGET", raising=False)
    if env is not None:
        monkeypatch.setenv("CODEBASE_BUDGET", env)
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("repo_path")
    add_arguments(parser)
    return parser.parse_args(["repo", *argv])


def assert_rejects_bad_budget(add_arguments, prog, monkeypatch, capsys, bad):
    with pytest.raises(SystemExit) as e:
        parse_with_budget(add_arguments, prog, ["--codebase-budget", bad], monkeypatch)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "--codebase-budget" in err and "CODEBASE_BUDGET" in err and repr(bad) in err


def assert_rejects_bad_budget_env(add_arguments, prog, monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        parse_with_budget(add_arguments, prog, [], monkeypatch, env="lots")
    assert e.value.code == 2
    assert "CODEBASE_BUDGET" in capsys.readouterr().err
