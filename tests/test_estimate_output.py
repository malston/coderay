"""What `crawl estimate-token-usage` prints once it estimates tokens and cost.

The crawl counts are covered by tests/test_estimate_token_usage.py. These cover
the estimate that sits under them.
"""
import subprocess
import sys

import pytest


def _repo(tmp_path):
    (tmp_path / "prisma").mkdir()
    (tmp_path / "prisma" / "schema.prisma").write_text(
        "model User {\n  id String @id\n}\n", encoding="utf-8")
    return tmp_path


def _run(tmp_path, *argv):
    import os
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")}
    env.pop("LLM_PROVIDER", None)
    return subprocess.run([sys.executable, "-m", "crawl.cli", "estimate-token-usage", *argv],
                          capture_output=True, text=True, env=env, cwd=str(tmp_path))


def test_it_reports_tokens_and_cost(tmp_path):
    out = _run(tmp_path, "schema", str(_repo(tmp_path))).stdout
    assert "input tokens" in out.lower()
    assert "output tokens" in out.lower()
    assert "$" in out, "a priced model should report a dollar figure"


def test_it_no_longer_says_it_does_not_estimate(tmp_path):
    """The line format_preview ended with while this was unimplemented."""
    out = _run(tmp_path, "schema", str(_repo(tmp_path))).stdout
    assert "does not yet estimate" not in out


def test_it_needs_no_api_key(tmp_path):
    """A user sizing a run before paying for it does not have to have paid yet.
    With no key and no LLM_PROVIDER, resolve_provider_and_model raises; the
    command still has to answer, and say which model it priced against."""
    r = _run(tmp_path, "schema", str(_repo(tmp_path)))
    assert r.returncode == 0, r.stderr
    assert "no LLM key" in r.stdout, "the reader should know the model was assumed"


def test_a_call_range_is_reported_as_a_range(tmp_path):
    """tour's chapter count is the model's answer, bounded by its own prompt."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    out = _run(tmp_path, "tour", str(tmp_path)).stdout
    assert "-" in out and "input tokens" in out.lower()


def test_notes_from_the_plan_reach_the_reader(tmp_path):
    """tour's bundle figure overstates, and the plan says so. A note nobody
    prints is a note nobody reads."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    out = _run(tmp_path, "tour", str(tmp_path)).stdout
    assert "coderay-3le" in out or "overstates" in out


def test_an_aborted_crawl_reports_no_estimate(tmp_path):
    """An empty repo: the crawl found nothing, so there is no run to size. The
    abort note still prints; an estimate of zero dollars would read as a real
    answer."""
    out = _run(tmp_path, "schema", str(tmp_path)).stdout
    assert "A real run stops here" in out
    assert "$" not in out


def test_the_estimate_goes_to_stdout_and_chatter_to_stderr(tmp_path):
    """Same rule the counts follow (coderay-pqj): stdout stays pipeable."""
    r = _run(tmp_path, "schema", str(_repo(tmp_path)))
    assert "input tokens" in r.stdout.lower()
    assert "input tokens" not in r.stderr.lower()


@pytest.mark.parametrize("analysis,expected_cap", [
    ("schema", 16384),        # ENV_DEFAULTS is empty; the shipped default applies
    ("backend", 32768),       # ENV_DEFAULTS raises LLM_MAX_OUTPUT_TOKENS
])
def test_the_output_cap_comes_from_the_analysis_not_the_ambient_environment(
        analysis, expected_cap, monkeypatch):
    """Four of the seven analyses raise LLM_MAX_OUTPUT_TOKENS through their own
    ENV_DEFAULTS. Reading the ambient value reports the wrong worst case for
    those four, and the two totals happen to coincide on a small repo, so this
    checks the cap itself rather than the printed total."""
    from crawl.analyses import ANALYSES
    from crawl.core.call_llm import max_output_tokens
    from crawl.core.env import env_defaults
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    with env_defaults(getattr(ANALYSES[analysis], "ENV_DEFAULTS", {})):
        assert max_output_tokens() == expected_cap


def test_a_users_own_output_cap_still_wins_over_the_analysis_default(monkeypatch):
    """env_defaults sets a key only when it is absent or blank."""
    from crawl.analyses import ANALYSES
    from crawl.core.call_llm import max_output_tokens
    from crawl.core.env import env_defaults
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "4096")
    with env_defaults(getattr(ANALYSES["backend"], "ENV_DEFAULTS", {})):
        assert max_output_tokens() == 4096


def test_tour_no_longer_takes_a_dry_run_flag(tmp_path):
    """It is `estimate-token-usage tour` now. The flag promised a cost estimate
    for one analysis; the command gives it for all seven."""
    import os
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")}
    r = subprocess.run([sys.executable, "-m", "crawl.cli", "tour", str(tmp_path), "--dry-run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2
    assert "unrecognized arguments" in r.stderr


# ---- ported from tour's --dry-run, which this command replaces ----

def test_it_reports_the_codebase_budget_it_sized_with(tmp_path):
    """Ported from test_dry_run_flag_reports_the_codebase_budget_it_would_use.
    coderay-5wu.15: a user comparing budgets needs to see which one produced
    the number in front of them."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    out = _run(tmp_path, "tour", str(tmp_path), "--codebase-budget", "2000000").stdout
    assert "2,000,000" in out


def test_tour_needs_no_api_key_either(tmp_path):
    """Ported from test_dry_run_flag_works_with_no_llm_key_configured."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    r = _run(tmp_path, "tour", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "$" in r.stdout


def test_it_writes_nothing_where_a_real_run_would(tmp_path):
    """Ported from test_dry_run_flag_estimates_without_creating_the_output_directory.
    The estimate refuses --out outright, so the check is that nothing appears."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    before = set(p.name for p in tmp_path.iterdir())
    _run(tmp_path, "tour", str(tmp_path))
    assert set(p.name for p in tmp_path.iterdir()) == before


def test_tour_worst_case_output_uses_the_cap_its_own_env_defaults_set(tmp_path, monkeypatch):
    """Ported from test_dry_run_estimates_worst_case_output_using_the_same_cap_as
    _the_real_run (coderay-5wu.26). The real run wraps its flow in
    env_defaults(ENV_DEFAULTS), raising LLM_MAX_OUTPUT_TOKENS to 32768; the
    estimate must use that cap, not the bare 16384 default, or its bound is half
    of what a real run could hit."""
    from crawl.analyses import ANALYSES
    from crawl.core.env import env_defaults
    from crawl.core.call_llm import max_output_tokens
    from crawl.core.estimate import estimate
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    class A:
        repo_path = str(tmp_path)
        codebase_budget = 1_000_000
        instructions = "beginner-tutorial"
    tour = ANALYSES["tour"]
    plan = tour.prompt_plan(A(), tour.preview(A()))
    with env_defaults(tour.ENV_DEFAULTS):
        cap = max_output_tokens()
    e = estimate(plan, "anthropic", "claude-sonnet-5", cap)
    calls = sum(p.calls[1] for p in plan)
    assert cap == 32768
    assert e["output_tokens_worst_case"] == 32768 * calls
