import pytest

import crack.core.llm as llm_module
import crack.analyses.tour.nodes as nodes_module
from crack.analyses.tour.nodes import Analyze, ExtractGraph, PipelineState, Relate, SmartCrawl


def test_pipeline_state_documents_every_key_the_nodes_use():
    expected = {
        "repo_path", "instructions",
        "preview_budget", "target_files", "codebase_budget", "chapter_context_window",
        "codebase", "selected_files", "selection_reasoning",
        "symbol_graph",
        "summary", "abstractions", "order",
        "relationships",
        "chapters", "filenames",
    }
    assert set(PipelineState.__annotations__) == expected


def test_extract_graph_builds_edges_for_known_extensions(tmp_path):
    (tmp_path / "main.py").write_text("from pkg.helper import go\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "helper.py").write_text("def go(): pass\n")
    shared = {
        "repo_path": str(tmp_path),
        "selected_files": ["main.py", "pkg/helper.py"],
    }
    prep_res = ExtractGraph().prep(shared)
    exec_res = ExtractGraph().exec(prep_res)
    ExtractGraph().post(shared, prep_res, exec_res)
    assert shared["symbol_graph"] == [{"from": "main.py", "to": "pkg/helper.py", "kind": "imports"}]


def test_extract_graph_skips_file_whose_extractor_raises(tmp_path, monkeypatch, capsys):
    (tmp_path / "broken.py").write_text("this won't actually parse but that's fine\n")
    (tmp_path / "main.py").write_text("from pkg.helper import go\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "helper.py").write_text("def go(): pass\n")

    real_python_extractor = nodes_module.REGISTRY[".py"]

    class RaisingExtractor:
        @staticmethod
        def imports(path, text, selected_files):
            if path == "broken.py":
                raise ValueError("simulated parse failure")
            return real_python_extractor.imports(path, text, selected_files)

    monkeypatch.setitem(nodes_module.REGISTRY, ".py", RaisingExtractor)

    shared = {
        "repo_path": str(tmp_path),
        "selected_files": ["broken.py", "main.py", "pkg/helper.py"],
    }
    prep_res = ExtractGraph().prep(shared)
    exec_res = ExtractGraph().exec(prep_res)  # must not raise
    ExtractGraph().post(shared, prep_res, exec_res)
    assert shared["symbol_graph"] == [{"from": "main.py", "to": "pkg/helper.py", "kind": "imports"}]
    _, covered = exec_res
    assert covered == 2, "broken.py's parse failure must not count toward coverage"
    assert "Skipping broken.py for import graph: simulated parse failure" in capsys.readouterr().out


def test_extract_graph_skips_files_with_no_registered_extractor(tmp_path):
    (tmp_path / "main.unknownlang").write_text("whatever this language is\n")
    shared = {
        "repo_path": str(tmp_path),
        "selected_files": ["main.unknownlang"],
    }
    prep_res = ExtractGraph().prep(shared)
    exec_res = ExtractGraph().exec(prep_res)
    ExtractGraph().post(shared, prep_res, exec_res)
    assert shared["symbol_graph"] == []


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
        "    files: []\n"
        "  - name: Foo\n"
        "    description: b\n"
        "    files: []\n"
        "learning_order:\n"
        "  - Foo\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="duplicate abstraction names"):
        Analyze().exec(("prompt", set()))


def test_analyze_rejects_abstraction_file_outside_selected_files(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "    files:\n"
        "      - not_selected.py\n"
        "learning_order:\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="not_selected.py"):
        Analyze().exec(("prompt", {"foo.py"}))


def test_analyze_rejects_non_list_abstractions(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions: not_a_list\n"
        "learning_order: []\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="must be a list"):
        Analyze().exec(("prompt", set()))


def test_analyze_rejects_non_list_files(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "    files: 5\n"
        "learning_order:\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="must be a list of strings"):
        Analyze().exec(("prompt", set()))


def test_analyze_rejects_missing_files_key(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "learning_order:\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="missing required field 'files'"):
        Analyze().exec(("prompt", set()))


def test_analyze_accepts_abstraction_files_within_selected_files(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "summary: a codebase\n"
        "abstractions:\n"
        "  - name: Foo\n"
        "    description: a\n"
        "    files:\n"
        "      - foo.py\n"
        "learning_order:\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    result = Analyze().exec(("prompt", {"foo.py"}))
    assert result["abstractions"][0]["files"] == ["foo.py"]


def test_analyze_retry_sends_a_different_prompt_each_time(monkeypatch, tmp_path):
    # Regression for coderay-2t7: the on-disk response cache keys on the exact
    # prompt, so a retry against identical malformed output would previously
    # just replay the same cached bad response. yaml_call varies the prompt
    # tail on each retry, which both produces a fresh call and defeats the
    # cache. Verify the prompts actually differ, not just that we eventually
    # raise.
    import importlib
    call_llm_module = importlib.import_module("crack.core.call_llm")

    monkeypatch.setattr(call_llm_module, "CACHE_DIR", str(tmp_path))
    prompts_seen = []

    def fake_call_llm(prompt):
        prompts_seen.append(prompt)
        return "not valid yaml, no fence"

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)
    with pytest.raises(AssertionError):
        Analyze().exec(("some prompt", set()))
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
        "    files: []\n"
        "  - name: Bar\n"
        "    description: b\n"
        "    files: []\n"
        "learning_order:\n"
        "  - Bar\n"
        "  - Foo\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    result = Analyze().exec(("prompt", {"Foo.py", "Bar.py"}))
    assert {a["name"] for a in result["abstractions"]} == {"Foo", "Bar"}


def test_relate_rejects_non_list_relationships(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "relationships: not_a_list\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="must be a list"):
        Relate().exec(("prompt", [], []))


def test_relate_rejects_edge_missing_a_required_field(monkeypatch):
    # relationships is LLM output (coderay-o41 review): an edge missing from/to/label
    # must fail here, at the point the data enters the pipeline, not crash a
    # downstream renderer that assumes every edge is well-formed.
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="label"):
        Relate().exec(("prompt", [], []))


def test_relate_rejects_non_string_label(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: 5\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    with pytest.raises(AssertionError, match="label"):
        Relate().exec(("prompt", [], []))


def test_relate_accepts_well_formed_relationships(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    result = Relate().exec(("prompt", [], []))
    assert result == [{"from": "Foo", "to": "Bar", "label": "uses", "source": "INFERRED"}]


def test_relate_tags_extracted_when_edge_matches_direction(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    abstractions = [{"name": "Foo", "files": ["foo.py"]}, {"name": "Bar", "files": ["bar.py"]}]
    symbol_graph = [{"from": "foo.py", "to": "bar.py", "kind": "imports"}]
    result = Relate().exec(("prompt", abstractions, symbol_graph))
    assert result == [{"from": "Foo", "to": "Bar", "label": "uses", "source": "EXTRACTED"}]


def test_relate_ignores_non_import_edge_kind(monkeypatch):
    # symbol_graph only ever holds "imports" edges today, but the check must
    # not silently trust a future edge kind (e.g. "calls") as EXTRACTED evidence.
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    abstractions = [{"name": "Foo", "files": ["foo.py"]}, {"name": "Bar", "files": ["bar.py"]}]
    symbol_graph = [{"from": "foo.py", "to": "bar.py", "kind": "calls"}]
    result = Relate().exec(("prompt", abstractions, symbol_graph))
    assert result == [{"from": "Foo", "to": "Bar", "label": "uses", "source": "INFERRED"}]


def test_relate_does_not_tag_extracted_for_reverse_direction_edge(monkeypatch):
    # bar.py imports foo.py is evidence for "Bar uses Foo", not "Foo uses Bar" --
    # tagging this EXTRACTED would be a wrong tag (post-review fix).
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    abstractions = [{"name": "Foo", "files": ["foo.py"]}, {"name": "Bar", "files": ["bar.py"]}]
    symbol_graph = [{"from": "bar.py", "to": "foo.py", "kind": "imports"}]  # reverse
    result = Relate().exec(("prompt", abstractions, symbol_graph))
    assert result == [{"from": "Foo", "to": "Bar", "label": "uses", "source": "INFERRED"}]


def test_relate_tags_inferred_when_no_matching_edge(monkeypatch):
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Bar\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    abstractions = [{"name": "Foo", "files": ["foo.py"]}, {"name": "Bar", "files": ["bar.py"]}]
    result = Relate().exec(("prompt", abstractions, []))
    assert result == [{"from": "Foo", "to": "Bar", "label": "uses", "source": "INFERRED"}]


def test_relate_tags_inferred_when_relationship_names_unknown_abstraction(monkeypatch):
    # "Baz" isn't in abstractions -- build_mermaid already drops this edge downstream
    # (crack/analyses/tour/render.py:68); the rollup has no file set to check, so INFERRED,
    # not an assertion (post-review fix).
    yaml_text = (
        "```yaml\n"
        "relationships:\n"
        "  - from: Foo\n"
        "    to: Baz\n"
        "    label: uses\n"
        "```"
    )
    monkeypatch.setattr(llm_module, "call_llm", lambda prompt: yaml_text)
    abstractions = [{"name": "Foo", "files": ["foo.py"]}]
    result = Relate().exec(("prompt", abstractions, []))
    assert result == [{"from": "Foo", "to": "Baz", "label": "uses", "source": "INFERRED"}]


def test_extract_graph_reads_an_uppercase_source_extension(tmp_path):
    """list_files accepts `.PY`, so a selected MAIN.PY must reach the Python
    extractor instead of falling through the unsupported-language branch."""
    (tmp_path / "MAIN.PY").write_text("from pkg.helper import go\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "helper.py").write_text("def go(): pass\n")
    shared = {
        "repo_path": str(tmp_path),
        "selected_files": ["MAIN.PY", "pkg/helper.py"],
    }
    prep_res = ExtractGraph().prep(shared)
    exec_res = ExtractGraph().exec(prep_res)
    ExtractGraph().post(shared, prep_res, exec_res)
    assert shared["symbol_graph"] == [{"from": "MAIN.PY", "to": "pkg/helper.py", "kind": "imports"}]
