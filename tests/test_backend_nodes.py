import pytest

from crawl.analyses.backend import nodes as n

CARDS = "### Route\nbody\n\n### Handler\nbody\n"

def test_build_bundle_populates_codebase_and_counts(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert "urlpatterns" in shared["codebase"]
    assert shared["layer_counts"]["route"] == 1

def test_build_bundle_rejects_a_repo_with_no_backend(tmp_path):
    """Was coderay-q2r.8, fixed upstream and re-ported at pin 34f0ad2.

    BuildBundle.post asserts `bundle.strip()` to reject a repo with no
    server-side backend, but build_bundle used to prepend a six-line layer-count
    header unconditionally, so the bundle was never empty, the guard never
    fired, and the run spent three LLM calls on a bundle of "0 files" lines.
    build_bundle now returns "" when it kept no files, so the guard stops the
    run. This matches the behaviour architecture has always had.
    """
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="No backend source found"):
        n.BuildBundle().run({"repo_path": str(tmp_path)})


def test_build_bundle_still_builds_a_bundle_when_it_finds_one_layer(tmp_path):
    """The empty-bundle return must not swallow a real, partial backend."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class User: pass\n", encoding="utf-8")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert shared["layer_counts"] == {"database": 1}
    assert "class User" in shared["codebase"]

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


def test_build_bundle_names_the_files_it_found_when_none_could_be_read(tmp_path):
    """coderay-q2r.57. safe_read leaves out a file that is not UTF-8, so a
    backend whose every layer file is Latin-1 gives non-zero counts and an
    empty bundle. The abort used to say "no routes/views/models", which its
    own counts contradicted."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "urls.py").write_bytes(b"urlpatterns = [] # caf\xe9\n")
    with pytest.raises(AssertionError, match=r"1 file.* route.*none .*unreadable or not UTF-8") as info:
        n.BuildBundle().run({"repo_path": str(tmp_path)})
    assert "No backend source found" not in str(info.value)


def test_build_bundle_abort_does_not_blame_encoding_for_an_unreadable_file(tmp_path):
    """PR #30 review. safe_read also drops a file it cannot open (permission
    denied, vanished), so the abort must not name UTF-8 as the only cause."""
    (tmp_path / "app").mkdir()
    p = tmp_path / "app" / "urls.py"
    p.write_text("urlpatterns = []\n", encoding="utf-8")
    p.chmod(0)
    try:
        with pytest.raises(AssertionError, match=r"Found 1 file in route.*unreadable"):
            n.BuildBundle().run({"repo_path": str(tmp_path)})
    finally:
        p.chmod(0o644)
