from crawl.core import OverviewNode, write_overview

SECTIONS = [("The pipeline", "the six layers"), ("The code", "the odd bits")]

REPLY = """## Welcome
toy_repo is a small Django service.

## The pipeline
Four routes fan into eleven handlers.

## The code
Only routing is unusual.
"""

def test_write_overview_splits_the_reply_into_welcome_and_intros(monkeypatch):
    monkeypatch.setattr("crawl.core.overview.call_llm", lambda prompt: REPLY)
    out = write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert out["welcome"] == "toy_repo is a small Django service."
    assert out["intros"]["The pipeline"] == "Four routes fan into eleven handlers."
    assert out["intros"]["The code"] == "Only routing is unusual."

def test_write_overview_falls_back_to_the_gist_for_a_missing_header(monkeypatch):
    monkeypatch.setattr("crawl.core.overview.call_llm",
                        lambda prompt: "## Welcome\nhi\n\n## The pipeline\nthere")
    out = write_overview("toy_repo", "a backend", SECTIONS)
    assert out["intros"]["The code"] == "the odd bits"

def test_write_overview_prompt_carries_the_name_facts_and_headers(monkeypatch):
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return REPLY

    monkeypatch.setattr("crawl.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert "toy_repo" in seen["p"]
    assert "4 routes" in seen["p"]
    assert "## The pipeline" in seen["p"]

def test_overview_node_stores_the_result_on_shared(monkeypatch):
    monkeypatch.setattr("crawl.core.overview.call_llm", lambda prompt: REPLY)
    shared = {"repo_path": "/tmp/toy_repo"}
    node = OverviewNode(lambda sh: {"name": "toy_repo", "what": "a backend",
                                    "sections": SECTIONS, "facts": ""})
    node.run(shared)
    assert shared["overview"]["welcome"] == "toy_repo is a small Django service."

def test_overview_node_leaves_empty_copy_when_the_call_keeps_failing(monkeypatch):
    def boom(prompt):
        raise RuntimeError("no api key")
    monkeypatch.setattr("crawl.core.overview.call_llm", boom)
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
    monkeypatch.setattr("crawl.core.overview.call_llm", boom)
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=1, wait=0)
    node.run({})
    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "rate limited" in out
    assert "without" in out.lower()

def test_overview_node_does_not_report_a_failure_on_success(monkeypatch, capsys):
    monkeypatch.setattr("crawl.core.overview.call_llm", lambda prompt: REPLY)
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

    monkeypatch.setattr("crawl.core.overview.call_llm", capture)
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

    monkeypatch.setattr("crawl.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS)
    assert "Cite the file and symbol" not in seen["p"]
    assert "## Welcome" in seen["p"] and "exactly as given" in seen["p"]


def test_overview_stays_non_fatal_when_the_reply_is_truncated(monkeypatch, capsys):
    """The overview is optional by design (coderay-q2r.13): a failure leaves the
    page without intro copy rather than killing the run. A deterministic LLM
    failure skips the node's retry loop, and so skips exec_fallback with it, so
    the node has to keep that promise itself (coderay-n9j)."""
    from crawl.core.call_llm import ResponseTruncated

    def truncated(prompt):
        raise ResponseTruncated("response truncated (stop_reason=max_tokens)")

    monkeypatch.setattr("crawl.core.overview.call_llm", truncated)
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=2, wait=0)
    shared = {}
    node.run(shared)

    assert shared["overview"] == {"welcome": "", "intros": {}}
    assert "Overview failed" in capsys.readouterr().out


def test_overview_stays_non_fatal_when_the_prompt_is_too_large(monkeypatch, capsys):
    """Same promise, for the other deterministic failure. The overview prompt
    carries counts and gists rather than source, so this is the unlikely one,
    but the node is documented as non-fatal without qualification."""
    from crawl.core.call_llm import PromptTooLarge

    def too_large(prompt):
        raise PromptTooLarge("prompt is about 9 tokens; lower --codebase-budget")

    monkeypatch.setattr("crawl.core.overview.call_llm", too_large)
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=2, wait=0)
    shared = {}
    node.run(shared)

    assert shared["overview"] == {"welcome": "", "intros": {}}
    assert "Overview failed" in capsys.readouterr().out


def test_a_truncated_overview_is_attempted_only_once(monkeypatch):
    """Retrying a truncation re-runs a whole generation to hit the same cap, and
    unlike an oversized prompt that one is billed every time."""
    from crawl.core.call_llm import ResponseTruncated

    attempts = []

    def truncated(prompt):
        attempts.append(1)
        raise ResponseTruncated("response truncated (stop_reason=max_tokens)")

    monkeypatch.setattr("crawl.core.overview.call_llm", truncated)
    OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                 max_retries=3, wait=0).run({})

    assert len(attempts) == 1
