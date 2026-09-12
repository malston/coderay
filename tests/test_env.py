import os

from crawl.core import env_defaults, load_dotenv

def test_sets_absent_key_and_restores_it():
    assert "CRAWL_TEST_ABSENT" not in os.environ
    with env_defaults({"CRAWL_TEST_ABSENT": "32768"}):
        assert os.environ["CRAWL_TEST_ABSENT"] == "32768"
    assert "CRAWL_TEST_ABSENT" not in os.environ

def test_a_value_the_user_already_set_wins(monkeypatch):
    monkeypatch.setenv("CRAWL_TEST_PRESENT", "mine")
    with env_defaults({"CRAWL_TEST_PRESENT": "theirs"}):
        assert os.environ["CRAWL_TEST_PRESENT"] == "mine"
    assert os.environ["CRAWL_TEST_PRESENT"] == "mine"

def test_restores_on_exception():
    try:
        with env_defaults({"CRAWL_TEST_RAISES": "1"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "CRAWL_TEST_RAISES" not in os.environ

def test_empty_defaults_is_a_no_op():
    before = dict(os.environ)
    with env_defaults({}):
        assert dict(os.environ) == before
    assert dict(os.environ) == before


def test_a_blank_value_counts_as_absent_and_is_restored_blank(monkeypatch):
    """Sourcing .env.example exports every knob as the empty string; the
    analysis default must still apply, and the blank must come back after."""
    import os
    from crawl.core.env import env_defaults
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "")
    with env_defaults({"LLM_MAX_OUTPUT_TOKENS": "32768"}):
        assert os.environ["LLM_MAX_OUTPUT_TOKENS"] == "32768"
    assert os.environ["LLM_MAX_OUTPUT_TOKENS"] == ""


# --- .env loading (coderay-ebq) ---------------------------------------------

def test_loads_a_key_from_dotenv_when_nothing_is_exported(tmp_path, monkeypatch):
    """The key has to reach the process that needs it without passing through
    the shell, or every process started in the repo inherits it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-the-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["ANTHROPIC_API_KEY"] == "from-the-file"


def test_a_real_environment_variable_wins_over_dotenv(tmp_path, monkeypatch):
    """CI sets its key as a real variable, and a one-off override on the command
    line has to beat the file it would otherwise read."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-shell")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-the-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["ANTHROPIC_API_KEY"] == "from-the-shell"


def test_a_missing_dotenv_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    load_dotenv()  # no .env here at all


def test_dotenv_is_read_from_the_working_directory_only(tmp_path, monkeypatch):
    """No upward search. `crawl tour .` inside someone else's checkout must not
    pick up the .env of a directory above it, which would send their key to a
    provider under this user's name."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-the-parent\n", encoding="utf-8")
    below = tmp_path / "nested"
    below.mkdir()
    monkeypatch.chdir(below)

    load_dotenv()

    assert "ANTHROPIC_API_KEY" not in os.environ


def test_dotenv_skips_comments_and_blank_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    (tmp_path / ".env").write_text(
        "# a comment\n\nANTHROPIC_API_KEY=k\nexport LLM_PROVIDER=anthropic\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["ANTHROPIC_API_KEY"] == "k"
    assert os.environ["LLM_PROVIDER"] == "anthropic"


def test_the_cli_loads_dotenv_before_it_parses_arguments(tmp_path, monkeypatch):
    """The loader is only worth having if the entry point calls it. Nothing else
    here would notice main() dropping the call."""
    import sys
    import pytest
    from crawl import cli

    probe = "CRAWL_DOTENV_WIRING_PROBE"
    monkeypatch.delenv(probe, raising=False)
    (tmp_path / ".env").write_text(f"{probe}=loaded\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["crawl"])

    try:
        with pytest.raises(SystemExit):  # argparse: no analysis given
            cli.main()
        assert os.environ[probe] == "loaded"
    finally:
        # load_dotenv writes straight to os.environ, which monkeypatch does not
        # track, so this one has to come back out by hand.
        os.environ.pop(probe, None)
