from crack.core import OverviewNode, write_overview

SECTIONS = [("The pipeline", "the six layers"), ("The code", "the odd bits")]

REPLY = """## Welcome
toy_repo is a small Django service.

## The pipeline
Four routes fan into eleven handlers.

## The code
Only routing is unusual.
"""

def test_write_overview_splits_the_reply_into_welcome_and_intros(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm", lambda prompt: REPLY)
    out = write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert out["welcome"] == "toy_repo is a small Django service."
    assert out["intros"]["The pipeline"] == "Four routes fan into eleven handlers."
    assert out["intros"]["The code"] == "Only routing is unusual."

def test_write_overview_falls_back_to_the_gist_for_a_missing_header(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm",
                        lambda prompt: "## Welcome\nhi\n\n## The pipeline\nthere")
    out = write_overview("toy_repo", "a backend", SECTIONS)
    assert out["intros"]["The code"] == "the odd bits"

def test_write_overview_prompt_carries_the_name_facts_and_headers(monkeypatch):
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return REPLY

    monkeypatch.setattr("crack.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert "toy_repo" in seen["p"]
    assert "4 routes" in seen["p"]
    assert "## The pipeline" in seen["p"]

def test_overview_node_stores_the_result_on_shared(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm", lambda prompt: REPLY)
    shared = {"repo_path": "/tmp/toy_repo"}
    node = OverviewNode(lambda sh: {"name": "toy_repo", "what": "a backend",
                                    "sections": SECTIONS, "facts": ""})
    node.run(shared)
    assert shared["overview"]["welcome"] == "toy_repo is a small Django service."

def test_overview_node_leaves_empty_copy_when_the_call_keeps_failing(monkeypatch):
    def boom(prompt):
        raise RuntimeError("no api key")
    monkeypatch.setattr("crack.core.overview.call_llm", boom)
    shared = {}
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=1, wait=0)
    node.run(shared)
    assert shared["overview"] == {"welcome": "", "intros": {}}
