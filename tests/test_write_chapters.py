"""coderay-q2r.46: WriteChapters and the output cap."""
import os

import pytest

import crawl.analyses.tour as tour
from crawl.analyses.tour import nodes as nodes_module
from crawl.core import max_output_tokens
from crawl.core.call_llm import ResponseTruncated

SHARED = {
    "abstractions": [{"name": "Hub", "description": "d1"}, {"name": "Claw", "description": "d2"}],
    "order": ["Hub", "Claw"],
    "codebase": "code",
    "instructions": "beginner-tutorial",
}


def test_write_chapters_does_not_retry_a_truncated_chapter(monkeypatch):
    """Mark hit this on a real run: chapter 9 of 10 overran the cap and the
    node re-wrote chapters 1-8 twice more before dying, eight minutes for
    nothing. Retrying a truncation cannot succeed, so it exits at once and
    names the chapter and the knob."""
    calls = []

    def fake(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise ResponseTruncated("Anthropic response truncated (stop_reason=max_tokens); "
                                    "raise LLM_MAX_OUTPUT_TOKENS (currently 16384)")
        return "chapter"

    monkeypatch.setattr(nodes_module, "call_llm", fake)
    shared = dict(SHARED)
    with pytest.raises(SystemExit) as e:
        nodes_module.WriteChapters().run(shared)
    assert len(calls) == 2
    assert shared["chapters"] == [{"name": "Hub", "filename": "01_hub.md", "content": "chapter"}]
    assert "Claw" in str(e.value) and "2/2" in str(e.value)
    assert "LLM_MAX_OUTPUT_TOKENS" in str(e.value)


def test_write_chapters_still_retries_a_transient_failure(monkeypatch):
    calls = []

    def fake(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("connection reset")
        return "chapter"

    monkeypatch.setattr(nodes_module, "call_llm", fake)
    node = nodes_module.WriteChapters()
    node.wait = 0
    shared = dict(SHARED)
    node.run(shared)
    assert len(shared["chapters"]) == 2
    assert len(calls) > 2


def test_tour_raises_the_output_cap_like_backend_does():
    assert tour.ENV_DEFAULTS == {"LLM_MAX_OUTPUT_TOKENS": "32768"}


def test_tour_run_applies_its_env_defaults_around_the_flow(tmp_path, monkeypatch):
    """Tour drives run_flow itself rather than run_analysis, so it has to
    apply ENV_DEFAULTS on its own."""
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr(tour, "resolve_provider_and_model", lambda: ("anthropic", "m"))
    monkeypatch.setattr(tour, "ensure_priced", lambda p, m: None)
    seen = {}

    class Stop(Exception):
        pass

    def fake_run_flow(flow, shared, out, dump):
        seen["cap"] = max_output_tokens()
        raise Stop

    monkeypatch.setattr(tour, "run_flow", fake_run_flow)
    args = type("A", (), {"repo_path": str(tmp_path), "instructions": "beginner-tutorial",
                          "dry_run": False, "out": str(tmp_path / "o"), "codebase_budget": 1_000_000})()
    with pytest.raises(Stop):
        tour.run(args)
    assert seen["cap"] == 32768
    assert "LLM_MAX_OUTPUT_TOKENS" not in os.environ


def test_a_retry_resumes_after_the_finished_chapters_and_keeps_them(monkeypatch):
    """coderay-5wu.3. A transient failure on chapter 2 must not rewrite chapter
    1 (paid once) nor drop it from shared if the outage outlasts the retries."""
    calls = []

    def fake(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("connection reset")
        return "body of " + str(len(calls))

    monkeypatch.setattr(nodes_module, "call_llm", fake)
    node = nodes_module.WriteChapters()
    node.wait = 0
    shared = dict(SHARED)
    node.run(shared)
    assert len(calls) == 3
    assert [c["content"] for c in shared["chapters"]] == ["body of 1", "body of 3"]


def test_finished_chapters_stay_in_shared_when_every_retry_fails(monkeypatch):
    calls = []

    def fake(prompt):
        calls.append(prompt)
        if len(calls) >= 2:
            raise RuntimeError("outage")
        return "body of 1"

    monkeypatch.setattr(nodes_module, "call_llm", fake)
    node = nodes_module.WriteChapters()
    node.wait = 0
    shared = dict(SHARED)
    with pytest.raises(RuntimeError, match="outage"):
        node.run(shared)
    assert shared["chapters"] == [{"name": "Hub", "filename": "01_hub.md", "content": "body of 1"}]
