import pytest

from crawl.analyses.architecture import nodes as n

CARDS = "### 1 · Gateway\nThe front door.\n\n### 2 · Auth\nAuth0.\n"


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_build_bundle_populates_the_codebase_and_the_stats(tmp_path):
    repo = _repo(tmp_path, {"docker-compose.yml": "services:\n  api:\n    image: api\n"})
    shared = {"repo_path": repo}
    n.BuildBundle().run(shared)
    assert "image: api" in shared["codebase"]
    assert shared["arch_stats"]["config_files"] == 1


def test_build_bundle_prints_why_sdk_imports_were_unavailable(tmp_path, capsys):
    """coderay-q2r.15: the run's own stats line names the missing evidence."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services:\n  api:\n    image: api\n"})
    n.BuildBundle().run({"repo_path": repo})
    assert "SDK imports unavailable: not a git repository" in capsys.readouterr().out


def test_build_bundle_refuses_a_repo_with_no_architecture_sources(tmp_path):
    """arch_crawl prepends no header, so an ordinary single-binary repo really
    does produce an empty bundle and the assertion stops the run before it
    spends three LLM calls on nothing.

    Backend's guard was dead for the opposite reason until coderay-q2r.8 was
    fixed upstream and re-ported; both are live now, and
    test_backend_nodes.py holds the other half of the pair.
    """
    repo = _repo(tmp_path, {"README.md": "# a single-binary tool\n"})
    with pytest.raises(SystemExit, match="No architecture sources found"):
        n.BuildBundle().run({"repo_path": repo})


def test_the_no_sources_guard_names_missing_sdk_evidence_too(tmp_path):
    """coderay-q2r.15. A code-only repo with SDK imports runs as a checkout
    (the bundle is the SDK section) and fails as a tarball; the guard must say
    the import evidence was unavailable, not only list four config sources
    that were never the problem."""
    repo = _repo(tmp_path, {"src/pay.ts": "import Stripe from 'stripe';\n"})
    with pytest.raises(SystemExit, match="SDK import evidence was also unavailable: not a git repository"):
        n.BuildBundle().run({"repo_path": repo})


def test_inventory_stores_the_markdown_the_diagram_and_the_verdict(monkeypatch):
    reply = ("**Shape verdict:** A gateway in front of four services.\n\n"
             "```mermaid\ngraph LR;\ngateway-->auth;\n```\n\n" + CARDS)
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Inventory().run(shared)
    assert shared["inventory_md"].startswith("**Shape verdict:**")
    assert shared["arch_diagram"] == "graph LR;\ngateway-->auth;"
    assert shared["shape_verdict"] == "A gateway in front of four services."


def test_inventory_takes_the_verdict_line_and_not_another_bold_run(monkeypatch):
    """The reply is full of bold text; only the labelled line is the verdict.

    The decoy comes first, so a naive "first **...**" read picks it up.
    """
    reply = ("**Note:** read the bands first.\n\n"
             "**Shape verdict:** A monolith with one worker.\n\n" + CARDS)
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Inventory().run(shared)
    assert shared["shape_verdict"] == "A monolith with one worker."


def test_inventory_leaves_the_verdict_and_diagram_empty_when_the_reply_has_neither(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.Inventory().run(shared)
    assert shared["shape_verdict"] == ""
    assert shared["arch_diagram"] == ""


@pytest.mark.parametrize("node_cls,key", [
    (n.Inventory, "inventory_md"),
    (n.TechStack, "techstack_md"),
    (n.TraceRequest, "trace_md"),
])
def test_every_llm_node_retries_a_reply_with_no_cards(monkeypatch, node_cls, key):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "prose, no cards" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = node_cls()
    node.wait = 0
    shared = {"codebase": "x", "inventory_md": CARDS}
    node.run(shared)
    assert len(calls) == 3
    assert shared[key] == CARDS.strip()


@pytest.mark.parametrize("node_cls,key", [
    (n.TechStack, "techstack_md"),
    (n.TraceRequest, "trace_md"),
])
def test_the_later_passes_are_given_the_inventory_so_all_three_name_the_same_nodes(
        monkeypatch, node_cls, key):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    inventory = "### 1 · Gateway\nThe front door.\n"
    node_cls().run({"codebase": "COMPOSE-BUNDLE", "inventory_md": inventory})
    assert inventory in prompts[0]
    assert "COMPOSE-BUNDLE" in prompts[0]


@pytest.mark.parametrize("name", ["inventory.md", "tech-stack.md", "trace-request.md"])
def test_every_prompt_loads_and_has_a_codebase_slot(name):
    assert "{codebase}" in n.load_prompt(name)


def test_the_codebase_slot_is_filled_before_the_prompt_goes_out(monkeypatch):
    prompts = []
    monkeypatch.setattr(n, "call_llm", lambda p: prompts.append(p) or CARDS)
    n.Inventory().run({"codebase": "COMPOSE-BUNDLE"})
    assert "{codebase}" not in prompts[0]
    assert "COMPOSE-BUNDLE" in prompts[0]


def test_the_no_sources_guard_speaks_to_the_reader_not_to_a_book(tmp_path):
    """coderay-5wu.17. The message reaches the user; a section marker from the
    course the analysis was ported from means nothing to them."""
    repo = _repo(tmp_path, {"README.md": "x\n"})
    with pytest.raises(SystemExit) as e:
        n.BuildBundle().run({"repo_path": repo})
    assert "§" not in str(e.value) and "single-binary tool" in str(e.value)
