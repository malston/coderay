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
