import pytest

from crack.analyses.backend import nodes as n

CARDS = "### Route\nbody\n\n### Handler\nbody\n"

def test_build_bundle_populates_codebase_and_counts(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert "urlpatterns" in shared["codebase"]
    assert shared["layer_counts"]["route"] == 1

def test_build_bundle_does_not_reject_a_repo_with_no_backend(tmp_path):
    """Known limitation, tracked as coderay-q2r.8.

    BuildBundle.post asserts `bundle.strip()` to reject a repo with no
    server-side backend, but build_bundle always prepends a six-line layer-count
    header, so the bundle is never empty and the guard never fires. The run
    proceeds and spends three LLM calls on a bundle of "0 files" lines.
    Inherited from the port source and deliberately not fixed here, because
    nodes.py is a near-verbatim copy. When upstream fixes it this test fails,
    which is the signal to re-port and invert it.
    """
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert shared["layer_counts"] == {}
    assert "route: 0 files" in shared["codebase"]

def test_pipeline_stores_markdown_and_the_diagram(monkeypatch):
    reply = "```mermaid\nflowchart LR\n  a --> b\n```\n\n" + CARDS
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Pipeline().run(shared)
    assert shared["pipeline_md"].startswith("```mermaid")
    assert shared["pipeline_diagram"] == "flowchart LR\n  a --> b"

def test_pipeline_leaves_the_diagram_empty_when_none_is_drawn(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.Pipeline().run(shared)
    assert shared["pipeline_diagram"] == ""

def test_pipeline_retries_a_reply_with_no_cards(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "no cards here" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = n.Pipeline()
    node.wait = 0
    shared = {"codebase": "x"}
    node.run(shared)
    assert len(calls) == 3
    assert shared["pipeline_md"] == CARDS.strip()

def test_layer_code_stores_markdown(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.LayerCode().run(shared)
    assert shared["layercode_md"] == CARDS.strip()

def test_trace_pulls_the_endpoint_out_of_the_reply(monkeypatch):
    reply = "**Endpoint:** POST /json/messages\n\n" + CARDS
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Trace().run(shared)
    assert shared["trace_endpoint"] == "POST /json/messages"

def test_trace_tolerates_a_reply_with_no_endpoint_line(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.Trace().run(shared)
    assert shared["trace_endpoint"] == ""

@pytest.mark.parametrize("name", ["pipeline.md", "layer-code.md", "trace.md"])
def test_every_prompt_loads_and_has_a_codebase_slot(name):
    text = n.load_prompt(name)
    assert "{codebase}" in text

def test_the_codebase_slot_is_filled(monkeypatch):
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return CARDS

    monkeypatch.setattr(n, "call_llm", capture)
    n.Pipeline().run({"codebase": "MARKER_TEXT"})
    assert "MARKER_TEXT" in seen["p"]
    assert "{codebase}" not in seen["p"]
