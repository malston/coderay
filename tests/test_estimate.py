"""The shared token and cost estimate (crawl/core/estimate.py).

Every analysis contributes a list of Prompt records; the math, the input-ceiling
check, and the pricing happen once, here.
"""
import pytest


def _p(**kw):
    from crawl.core.estimate import Prompt
    base = dict(template="t.md", shell_chars=1000, body_chars=0, calls=(1, 1))
    return Prompt(**{**base, **kw})


def test_input_tokens_count_every_call_of_every_prompt():
    from crawl.core.estimate import estimate
    e = estimate([_p(shell_chars=400, body_chars=400, calls=(3, 3))],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=100)
    # 800 chars a call at 4 chars per token, three calls.
    assert e["input_tokens"] == (600, 600)


def test_a_call_range_becomes_an_input_token_range():
    from crawl.core.estimate import estimate
    e = estimate([_p(shell_chars=400, body_chars=400, calls=(2, 5))],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=100)
    assert e["input_tokens"] == (400, 1000)


def test_worst_case_output_is_the_cap_times_the_highest_call_count():
    from crawl.core.estimate import estimate
    e = estimate([_p(calls=(2, 5))], provider="anthropic", model="claude-sonnet-5",
                 max_output_tokens=32768)
    assert e["output_tokens_worst_case"] == 32768 * 5


def test_cost_is_a_low_high_pair_for_a_priced_model():
    from crawl.core.estimate import estimate
    e = estimate([_p(shell_chars=4000, calls=(1, 1))],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=1000)
    assert e["cost"][0] is not None and e["cost"][1] is not None
    # The low end buys no output tokens; the high end buys the worst case.
    assert e["cost"][1] > e["cost"][0]


def test_cost_is_none_for_a_model_with_no_pricing():
    from crawl.core.estimate import estimate
    e = estimate([_p()], provider="anthropic", model="no-such-model",
                 max_output_tokens=1000)
    assert e["cost"] == (None, None)


def test_the_largest_prompt_is_measured_against_the_model_s_input_ceiling():
    from crawl.core.estimate import estimate
    from crawl.core.pricing import input_ceiling
    ceiling = input_ceiling("anthropic", "claude-sonnet-5")
    assert ceiling, "this test needs a model with a recorded ceiling"
    e = estimate([_p(shell_chars=10), _p(body_chars=ceiling * 100)],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=100)
    assert e["over_ceiling"] is True
    assert e["input_ceiling"] == ceiling


def test_a_run_that_fits_is_not_reported_as_over_the_ceiling():
    from crawl.core.estimate import estimate
    e = estimate([_p(shell_chars=1000)], provider="anthropic",
                 model="claude-sonnet-5", max_output_tokens=100)
    assert e["over_ceiling"] is False


def test_an_unrecorded_ceiling_is_not_reported_as_fitting():
    """None means unchecked, not unlimited (the rule pricing.input_ceiling sets)."""
    from crawl.core.estimate import estimate
    e = estimate([_p()], provider="anthropic", model="no-such-model",
                 max_output_tokens=100)
    assert e["input_ceiling"] is None
    assert e["over_ceiling"] is None


def test_prompt_notes_are_carried_through_for_the_reader():
    from crawl.core.estimate import estimate
    e = estimate([_p(note="the bundle is LLM-picked and not counted here")],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=100)
    assert "the bundle is LLM-picked and not counted here" in e["notes"]


def test_calls_low_may_be_zero_for_a_prompt_that_might_not_fire():
    """schema's migration-acts below MIGRATION_FLOOR, and the graveyard pass on a
    repo with no bulk deletions. Zero is a real answer, not a missing one."""
    from crawl.core.estimate import estimate
    e = estimate([_p(shell_chars=4000, calls=(0, 1))],
                 provider="anthropic", model="claude-sonnet-5", max_output_tokens=100)
    assert e["input_tokens"][0] == 0
    assert e["input_tokens"][1] == 1000


# ---- ported from tour's --dry-run tests, which covered the same behaviour ----

def test_an_unpriced_model_is_reported_as_unknown_rather_than_free():
    """Ported from test_format_dry_run_summary_shows_unknown_for_an_unpriced_model.
    A blank cost line would read as free."""
    from crawl.core.estimate import estimate, format_estimate
    out = format_estimate(estimate([_p()], "openai", "gpt-6-mystery", 1000))
    assert "unknown" in out
    assert "$" not in out


def test_the_codebase_budget_is_reported_when_one_sized_the_run():
    """Ported from test_format_dry_run_summary_reports_the_codebase_budget
    (coderay-5wu.15)."""
    from crawl.core.estimate import estimate, format_estimate
    out = format_estimate(estimate([_p()], "anthropic", "claude-sonnet-5", 1000),
                          codebase_budget=2_000_000)
    assert "2,000,000" in out


def test_a_refused_run_says_so_with_both_figures_and_the_way_out():
    """Ported from test_dry_run_says_when_a_run_would_be_refused_before_it_starts
    (coderay-8vk). The command whose job is to say what a run will do should not
    stay quiet about the run not happening at all."""
    from crawl.core.estimate import estimate, format_estimate
    from crawl.core.pricing import input_ceiling
    ceiling = input_ceiling("anthropic", "claude-sonnet-5")
    out = format_estimate(estimate([_p(body_chars=ceiling * 100)], "anthropic",
                                   "claude-sonnet-5", 1000))
    assert "would be refused before its first call" in out
    assert f"{ceiling:,}" in out
    assert "--codebase-budget" in out


def test_a_run_that_fits_says_nothing_about_refusal():
    """Ported from test_dry_run_stays_quiet_when_the_prompts_fit."""
    from crawl.core.estimate import estimate, format_estimate
    out = format_estimate(estimate([_p()], "anthropic", "claude-sonnet-5", 1000))
    assert "would be refused" not in out


def test_an_unrecorded_ceiling_is_said_out_loud():
    """Ported from test_dry_run_says_when_no_ceiling_is_recorded_for_the_model.
    Unknown is not the same answer as fits."""
    from crawl.core.estimate import estimate, format_estimate
    out = format_estimate(estimate([_p()], "anthropic", "no-such-model", 1000))
    assert "No input ceiling is recorded" in out


def test_the_ceiling_check_uses_the_guards_own_divisor_not_the_pricing_one():
    """Ported from test_dry_run_sizes_prompts_with_the_guard_s_own_divisor
    (coderay-8vk). The refusal prediction answers "will call_llm's guard refuse
    this", so it has to use that guard's divisor. The cost figure beside it uses
    chars/4, and the two are deliberately different."""
    from crawl.core import estimate as est
    from crawl.core.call_llm import CHARS_PER_TOKEN
    assert est.PRICING_CHARS_PER_TOKEN != CHARS_PER_TOKEN
    e = est.estimate([_p(shell_chars=10_000, body_chars=0)], "anthropic",
                     "claude-sonnet-5", 1000)
    assert e["largest_prompt_tokens"] == int(10_000 / CHARS_PER_TOKEN)
    assert e["input_tokens"][1] == 10_000 // est.PRICING_CHARS_PER_TOKEN


def test_a_bigger_codebase_budget_makes_a_bigger_estimate(tmp_path):
    """Ported from test_estimate_dry_run_cost_honours_the_codebase_budget. The
    budget has to reach the numbers, not just the line that reports it."""
    from crawl.analyses import ANALYSES
    from crawl.core.estimate import estimate
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("x = 1\n" * 100, encoding="utf-8")

    def sized(budget):
        class A:
            repo_path = str(tmp_path)
            codebase_budget = budget
            instructions = "beginner-tutorial"
        tour = ANALYSES["tour"]
        plan = tour.prompt_plan(A(), tour.preview(A()))
        return estimate(plan, "anthropic", "claude-sonnet-5", 1000)["input_tokens"][1]

    assert sized(100) < sized(100_000)
