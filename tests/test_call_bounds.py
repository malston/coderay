"""The call-count bounds an estimate uses, pinned to the prompts that state them.

Three of the seven analyses send a prompt a variable number of times, and the
model decides the number. Each count is bounded by the prompt that asks for it,
so the estimate reports a range rather than a guess. The constant holding each
range lives beside its analysis; these tests fail with the constant named when a
prompt is reworded out from under it.
"""
from crawl.core import read_prompt


def _prompt(analysis, name):
    import importlib, pathlib
    root = pathlib.Path(importlib.import_module("crawl").__file__).parent
    return read_prompt(root / "analyses" / analysis / "prompts", name)


def test_chapter_range_matches_what_the_abstractions_prompt_asks_for():
    from crawl.analyses.tour.nodes import CHAPTER_RANGE
    low, high = CHAPTER_RANGE
    text = _prompt("tour", "identify-abstractions.md")
    assert f"{low} to {high}" in text, (
        f"identify-abstractions.md no longer asks for '{low} to {high}' abstractions. "
        f"CHAPTER_RANGE in analyses/tour/nodes.py claims it does; update the constant.")


def test_era_range_matches_what_the_name_eras_prompt_asks_for():
    from crawl.analyses.git_history.nodes import ERA_RANGE
    low, high = ERA_RANGE
    text = _prompt("git_history", "name-eras.md")
    assert f"{low}-{high} named ERAS" in text, (
        f"name-eras.md no longer asks for '{low}-{high} named ERAS'. "
        f"ERA_RANGE in analyses/git_history/nodes.py claims it does; update the constant.")


def test_table_estimate_matches_what_the_schema_tour_prompt_asks_for():
    from crawl.analyses.schema.nodes import TABLE_ESTIMATE
    text = _prompt("schema", "schema-tour.md")
    assert f"about {TABLE_ESTIMATE} tables" in text, (
        f"schema-tour.md no longer asks for 'about {TABLE_ESTIMATE} tables'. "
        f"TABLE_ESTIMATE in analyses/schema/nodes.py claims it does; update the constant.")


def test_graveyard_keeps_no_more_than_max_graves_when_nothing_sets_it(monkeypatch):
    """Unlike the three above, this bound is a flag default rather than prompt
    text, so it is pinned to what Graveyard.prep actually keeps. Hand it twice
    MAX_GRAVES distinct candidates and count what survives."""
    from crawl.analyses.git_history import nodes as gh
    monkeypatch.setattr(gh.gl, "is_pure_rename", lambda *a, **k: False)
    candidates = [{"hash": f"{i:040x}", "count": 50 - i, "scope": f"area{i}",
                   "subject": f"delete {i}", "month": "2026-01",
                   "files": [f"src/area{i}/gone.py"]}
                  for i in range(gh.MAX_GRAVES * 2)]
    ctx = gh.Graveyard().prep(
        {"bulk_dels": candidates, "repo_path": ".", "eras": [], "graves": []})
    assert len(ctx["graves"]) == gh.MAX_GRAVES, (
        f"Graveyard.prep kept {len(ctx['graves'])} graves from "
        f"{len(candidates)} candidates, but MAX_GRAVES in "
        f"analyses/git_history/nodes.py claims the ceiling is {gh.MAX_GRAVES}.")
