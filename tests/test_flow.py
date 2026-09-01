import crack.core.llm as llm_module
import workflow.nodes as nodes_module
from workflow.flow import create_tour_flow


def test_full_pipeline_tags_relationships(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("from pkg.helper import go\ngo()\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "helper.py").write_text("def go(): pass\n")

    responses = iter([
        # SmartCrawl
        "```yaml\nselected: [0, 1]\nreasoning: both matter\n```",
        # Analyze
        (
            "```yaml\n"
            "summary: a tiny repo\n"
            "abstractions:\n"
            "  - name: Main\n"
            "    description: entry point\n"
            "    files: [main.py]\n"
            "  - name: Helper\n"
            "    description: does the work\n"
            "    files: [pkg/helper.py]\n"
            "learning_order: [Helper, Main]\n"
            "```"
        ),
        # Relate
        (
            "```yaml\n"
            "relationships:\n"
            "  - from: Main\n"
            "    to: Helper\n"
            "    label: calls\n"
            "```"
        ),
        # WriteChapters (2 chapters, plain text, not YAML)
        "# Chapter 1: Helper\ncontent",
        "# Chapter 2: Main\ncontent",
    ])
    fake_call_llm = lambda prompt: next(responses)
    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)
    monkeypatch.setattr(nodes_module, "call_llm", fake_call_llm)

    shared = {"repo_path": str(tmp_path), "instructions": "beginner-tutorial"}
    create_tour_flow().run(shared)

    assert shared["symbol_graph"] == [{"from": "main.py", "to": "pkg/helper.py", "kind": "imports"}]
    assert shared["relationships"] == [
        {"from": "Main", "to": "Helper", "label": "calls", "source": "EXTRACTED"}
    ]
