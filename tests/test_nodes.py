import pytest

import utils.llm as llm_module
from workflow.nodes import Analyze, SmartCrawl


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
