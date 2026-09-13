"""Every analysis contributes a prompt plan, and none of them calls an LLM to do it.

The plan is what crawl.core.estimate turns into tokens and dollars. It is built
from the Preview the command already computed, so the repo is crawled once.
"""
import os
import pytest

from crawl.analyses import ANALYSES


def _args(repo_path, **over):
    class A:
        pass
    a = A()
    a.repo_path = repo_path
    a.codebase_budget = 650_000
    a.schema = None
    a.instructions = "beginner-tutorial"
    a.include = []
    a.exclude = []
    for k, v in over.items():
        setattr(a, k, v)
    return a


@pytest.fixture
def repo(tmp_path):
    """A repo with something for every crawler to find."""
    (tmp_path / "prisma").mkdir()
    (tmp_path / "prisma" / "schema.prisma").write_text(
        "model User {\n  id String @id\n  email String\n}\n", encoding="utf-8")
    (tmp_path / "server.js").write_text(
        "const express = require('express');\napp.get('/api/users', handler);\n",
        encoding="utf-8")
    (tmp_path / "package.json").write_text('{"dependencies":{"express":"4"}}', encoding="utf-8")
    import subprocess
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t",
                    "-c", "user.email=t@e.com", "commit", "-qm", "first"],
                   check=True, capture_output=True)
    return str(tmp_path)


@pytest.mark.parametrize("name", sorted(ANALYSES))
def test_every_analysis_declares_a_prompt_plan(name):
    assert callable(getattr(ANALYSES[name], "prompt_plan", None)), (
        f"{name} has no prompt_plan(args, preview); "
        "estimate-token-usage cannot size its run")


@pytest.mark.parametrize("name", sorted(ANALYSES))
def test_a_prompt_plan_returns_prompt_records(name, repo):
    from crawl.core.estimate import Prompt
    analysis = ANALYSES[name]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    assert plan, f"{name} returned an empty plan"
    for p in plan:
        assert isinstance(p, Prompt), f"{name} returned a {type(p).__name__}"
        assert p.shell_chars > 0, f"{name}/{p.template} has no template text"
        assert p.calls[0] <= p.calls[1], f"{name}/{p.template} has calls low > high"
        assert p.body_chars >= 0, f"{name}/{p.template} has negative body chars"


@pytest.mark.parametrize("name", sorted(ANALYSES))
def test_a_prompt_plan_makes_no_llm_call(name, repo):
    """Patching call_llm does not prove this: every nodes module binds its own
    name at import. The usage ledger is the only witness, and it records a
    disk-cache hit too."""
    from crawl.core.call_llm import get_usage, reset_usage
    analysis = ANALYSES[name]
    preview = analysis.preview(_args(repo))
    reset_usage()
    analysis.prompt_plan(_args(repo), preview)
    assert get_usage() == [], f"{name}'s prompt_plan called an LLM"


def test_schema_plans_no_migration_call_when_the_repo_is_below_the_floor(repo):
    """uigen-shaped: a schema and no migrations at all. The acts prompt is never
    built, so its low and high are both zero rather than an assumed one."""
    analysis = ANALYSES["schema"]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    acts = [p for p in plan if "migration" in p.template]
    assert acts, "schema's plan omitted the migration prompt entirely"
    assert acts[0].calls == (0, 0)


def test_schema_sizes_its_deep_dive_batches_from_the_table_bound(repo):
    """TABLE_ESTIMATE tables over TableDeepDive.BATCH per call. The real count
    comes from SchemaTour's diagram, which no pre-flight step has, so the plan
    carries a note saying the figure is the prompt's target."""
    from crawl.analyses.schema.nodes import BATCH_ESTIMATE
    analysis = ANALYSES["schema"]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    deep = [p for p in plan if "deep-dive" in p.template][0]
    assert deep.calls == (BATCH_ESTIMATE, BATCH_ESTIMATE)
    assert deep.note, "the batch count is an assumption and should say so"


def test_tour_reports_a_chapter_range_rather_than_one_number(repo):
    from crawl.analyses.tour.nodes import CHAPTER_RANGE
    analysis = ANALYSES["tour"]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    chapter = [p for p in plan if "write-chapter" in p.template][0]
    assert chapter.calls == CHAPTER_RANGE


def test_tour_says_its_codebase_bundle_is_an_estimate(repo):
    """The bundle is built from files the model picks, so no preview can size it
    (coderay-3le). Saying so beats reporting a number as if it were measured."""
    analysis = ANALYSES["tour"]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    assert any(p.note for p in plan), "tour's plan claims a measured bundle"


def test_a_crawl_that_found_nothing_has_no_run_to_estimate(tmp_path):
    """A git checkout with no commits. The preview reports the abort rather than
    raising, and a caller asking for a plan anyway would size a run that never
    happens. `aborted` is the one place that note is matched."""
    import subprocess
    from crawl.core.preview import aborted
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True,
                   capture_output=True)
    preview = ANALYSES["git-history"].preview(_args(str(tmp_path)))
    assert aborted(preview) is True


def test_a_crawl_that_found_something_is_not_reported_as_aborted(repo):
    from crawl.core.preview import aborted
    analysis = ANALYSES["schema"]
    assert aborted(analysis.preview(_args(repo))) is False
