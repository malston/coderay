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

def test_overview_node_reports_the_failure_instead_of_staying_silent(monkeypatch, capsys):
    # coderay-q2r.13: exec_fallback used to discard the exception, so a rate
    # limit on the last call of the run left the page without intro copy and
    # printed nothing at all.
    def boom(prompt):
        raise RuntimeError("rate limited")
    monkeypatch.setattr("crack.core.overview.call_llm", boom)
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=1, wait=0)
    node.run({})
    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "rate limited" in out
    assert "without" in out.lower()

def test_overview_node_does_not_report_a_failure_on_success(monkeypatch, capsys):
    monkeypatch.setattr("crack.core.overview.call_llm", lambda prompt: REPLY)
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS})
    node.run({})
    out = capsys.readouterr().out
    assert "Overview written" in out
    assert "failed" not in out.lower()


def test_write_overview_prompt_carries_the_house_style(monkeypatch):
    """coderay-aph: the overview prompt used to restate the voice rules."""
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return REPLY

    monkeypatch.setattr("crack.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS)
    assert "concrete nouns" in seen["p"]
    assert "{house_style}" not in seen["p"]
    assert '("seamless", "powerful"' not in seen["p"]   # the old inline banned-word list is gone


def test_write_overview_prompt_asks_for_voice_but_not_citations(monkeypatch):
    """Codex review of PR #33. The overview has counts and section gists, no
    source, so the evidence rules stay out; the `## Welcome` header it
    requires is exempt from the ban on "welcome"."""
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return REPLY

    monkeypatch.setattr("crack.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS)
    assert "Cite the file and symbol" not in seen["p"]
    assert "## Welcome" in seen["p"] and "exactly as given" in seen["p"]
