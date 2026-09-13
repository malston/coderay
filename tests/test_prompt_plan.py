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


def test_git_history_sizes_from_the_flags_it_was_given(repo):
    """The estimate subcommand accepts --profile-diff-chars, --max-graves and
    the rest, so a plan that reads the module defaults instead prices a run
    nobody asked for. Measured: at 50,000 chars a diff and 50 graves, a real
    run sends far more than the defaults would suggest."""
    analysis = ANALYSES["git-history"]
    default = _args(repo, profile_max_commits=400, profile_diff_chars=2500,
                    max_graves=6, grave_min_files=8)
    configured = _args(repo, profile_max_commits=4000, profile_diff_chars=50_000,
                       max_graves=50, grave_min_files=8)
    d = {p.template: p for p in analysis.prompt_plan(default, analysis.preview(default))}
    c = {p.template: p for p in analysis.prompt_plan(configured, analysis.preview(configured))}
    assert c["profile-era.md"].body_chars > d["profile-era.md"].body_chars
    assert c["graveyard-entry.md"].calls == (0, 50)
    assert d["graveyard-entry.md"].calls == (0, 6)
    # There is no --grave-diff-chars flag; GRAVE_DIFF_CHARS is fixed, so only
    # the call count moves for that prompt.
    assert c["graveyard-entry.md"].body_chars == d["graveyard-entry.md"].body_chars


def test_a_git_history_flag_reaches_both_the_run_and_the_estimate(repo):
    """The number the estimate prices has to be the number the run sends. Each
    of these used to be stated in three places: the flag default, init_shared's
    getattr fallback, and the constant. This checks the value a user actually
    passes arrives at both ends."""
    import argparse
    from crawl.analyses.git_history import add_arguments, init_shared, prompt_plan, preview
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    add_arguments(parser)
    args = parser.parse_args([repo, "--profile-diff-chars", "7777",
                              "--profile-max-commits", "88", "--max-graves", "3"])
    shared = init_shared(args)
    assert shared["profile_diff_chars"] == 7777
    assert shared["profile_max_commits"] == 88
    assert shared["max_graves"] == 3

    plan = {p.template: p for p in prompt_plan(args, preview(args))}
    assert plan["profile-era.md"].body_chars >= 5 * 7777, "the estimate ignored the flag"
    assert plan["graveyard-entry.md"].calls == (0, 3)


def test_tour_counts_the_instructions_lens_it_was_given(repo):
    """--instructions picks a lens whose text fills {instructions} in every
    chapter prompt. The lenses differ by hundreds of bytes, so an estimate that
    ignores the flag reports the same number for all of them."""
    analysis = ANALYSES["tour"]
    a = _args(repo, instructions="beginner-tutorial")
    b = _args(repo, instructions="security-audit")
    pa = [p for p in analysis.prompt_plan(a, analysis.preview(a)) if "write-chapter" in p.template][0]
    pb = [p for p in analysis.prompt_plan(b, analysis.preview(b)) if "write-chapter" in p.template][0]
    assert pa.body_chars != pb.body_chars


def test_the_interfaces_pick_prompt_says_what_it_cannot_size(repo):
    """_PICK_PROMPT carries ApiMenu's whole markdown output in {menu}, which is
    that pass's own answer. The estimate's rule is absent and said, never
    silently zero."""
    analysis = ANALYSES["interfaces"]
    plan = analysis.prompt_plan(_args(repo), analysis.preview(_args(repo)))
    pick = [p for p in plan if "PICK" in p.template][0]
    assert pick.note, "the pick prompt drops the feature menu without saying so"


def test_tour_sizes_its_bundle_from_what_a_run_sends_not_the_repository(repo):
    """coderay-3le, fixed on main in PR #115. A run bundles the target_files the
    model picks, not every readable file. The plan reads
    estimated_codebase_chars, so the two agree."""
    from crawl.analyses.tour.render import estimated_codebase_chars
    from crawl.analyses.tour.nodes import target_count
    analysis = ANALYSES["tour"]
    args = _args(repo)
    preview = analysis.preview(args)
    plan = {p.template: p for p in analysis.prompt_plan(args, preview)}

    paths = [os.path.join(repo, f) for f in preview["included"]]
    expected = estimated_codebase_chars(paths, repo, args.codebase_budget)
    assert plan["identify-abstractions.md"].body_chars == expected.likely


def test_tour_measures_the_ceiling_against_the_most_a_run_could_send(repo):
    """The cost figure should be the expectation and the refusal prediction has
    to be the ceiling, or the guard whose job is to speak before a run is
    refused is the thing that stays quiet (coderay-8vk)."""
    analysis = ANALYSES["tour"]
    args = _args(repo)
    plan = {p.template: p for p in analysis.prompt_plan(args, analysis.preview(args))}
    p = plan["identify-abstractions.md"]
    assert p.ceiling_chars >= p.chars_per_call, (
        "the ceiling figure must not sit under the likely one")


def test_a_prompt_with_no_separate_ceiling_uses_its_own_size(repo):
    """Six analyses know exactly what they send, so likely and most coincide."""
    analysis = ANALYSES["schema"]
    args = _args(repo)
    for p in analysis.prompt_plan(args, analysis.preview(args)):
        assert p.ceiling_chars == p.chars_per_call


def test_tour_says_when_its_figure_rests_on_few_readable_files(tmp_path):
    """Ported from _dry_run_unreadable_note (PR #115). A run is not refused for
    this: post skips every file it cannot read and every call goes out against
    an empty codebase, paid for at the quoted figure. No other line says so."""
    import subprocess
    (tmp_path / "a.py").write_bytes(b"\xff\xfe\x00bad")
    (tmp_path / "b.py").write_bytes(b"\xff\xfe\x00bad")
    analysis = ANALYSES["tour"]
    args = _args(str(tmp_path))
    plan = analysis.prompt_plan(args, analysis.preview(args))
    notes = " ".join(p.note for p in plan)
    assert "could be read" in notes, (
        "a figure resting on unreadable files should say so")
