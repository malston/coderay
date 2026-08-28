import pytest

import coderay_utils.llm as llm_module
from workflow.nodes import Analyze, PipelineState, SmartCrawl


def test_pipeline_state_documents_every_key_the_nodes_use():
    expected = {
        "repo_path", "instructions",
        "preview_budget", "target_files", "codebase_budget", "chapter_context_window",
        "codebase", "selected_files", "selection_reasoning",
        "summary", "abstractions", "order",
        "relationships",
        "chapters", "filenames",
    }
    assert set(PipelineState.__annotations__) == expected


def _make_files(tmp_path, count, size=2000):
    for i in range(count):
        (tmp_path / f"file_{i}.py").write_text("x" * size)


def test_smart_crawl_caps_file_count_to_budget(tmp_path):
    _make_files(tmp_path, count=50)
    shared = {"repo_path": str(tmp_path), "preview_budget": 4000}
    prompt, files, root = SmartCrawl().prep(shared)
    # budget=4000 // PREVIEW_CHARS_PER_FILE(800) = 5 files max, regardless of the
    # 50 files on disk -- this is the fix for the preview-budget floor bug.
    assert len(files) == 5
    assert len(prompt) < 4000 + 2000  # manifest bounded, not proportional to 50 files


def test_smart_crawl_post_enforces_codebase_budget(tmp_path):
    _make_files(tmp_path, count=10, size=1000)
    selected = sorted(tmp_path.glob("file_*.py"))
    shared = {"repo_path": str(tmp_path), "codebase_budget": 3000}
    SmartCrawl().post(shared, None, (selected, "because"))
    assert len(shared["codebase"]) < 10 * 1000
    assert len(shared["selected_files"]) < 10


def test_analyze_rejects_duplicate_abstraction_names(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "  - name: Foo\n"
        "    description: b\n"
        "learning_order:\n"
        "  - Foo\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="duplicate abstraction names"):
        Analyze().exec("prompt")


def test_analyze_retry_sends_a_different_prompt_each_time(monkeypatch, tmp_path):
    # Regression for coderay-2t7: the on-disk response cache keys on the exact
    # prompt, so a retry against identical malformed output would previously
    # just replay the same cached bad response. yaml_call varies the prompt
    # tail on each retry, which both produces a fresh call and defeats the
    # cache. Verify the prompts actually differ, not just that we eventually
    # raise.
    import importlib
    call_llm_module = importlib.import_module("coderay_utils.call_llm")

    monkeypatch.setattr(call_llm_module, "CACHE_DIR", str(tmp_path))
    prompts_seen = []

    def fake_call_llm(prompt):
        prompts_seen.append(prompt)
        return "not valid yaml, no fence"

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)
    with pytest.raises(AssertionError):
        Analyze().exec("some prompt")
    assert len(prompts_seen) > 1
    assert len(set(prompts_seen)) == len(prompts_seen), \
        "retries sent an identical prompt -- cache would serve the stale bad response"


def test_analyze_accepts_matching_names_and_order(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "  - name: Bar\n"
        "    description: b\n"
        "learning_order:\n"
        "  - Bar\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    result = Analyze().exec("prompt")
    assert {a["name"] for a in result["abstractions"]} == {"Foo", "Bar"}
