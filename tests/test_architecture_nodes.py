import os

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


def test_build_bundle_prints_when_config_files_were_found_but_not_included(tmp_path, capsys):
    """coderay-5wu.6. config_files_found was computed but never shown anywhere
    a human reads."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n",
                            "docker-compose.override.yml": ""})
    n.BuildBundle().run({"repo_path": repo})
    assert "more config files found but not in the bundle" in capsys.readouterr().out


def test_build_bundle_prints_when_a_package_json_was_malformed(tmp_path, capsys):
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n", "package.json": "{not json"})
    n.BuildBundle().run({"repo_path": repo})
    assert "package.json malformed" in capsys.readouterr().out


def test_build_bundle_prints_when_a_package_json_was_unreadable(tmp_path, capsys):
    outside = tmp_path / "outside.json"
    outside.write_text('{"dependencies": {"left-out": "^1"}}', encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"docker-compose.yml": "services: {}\n"})
    os.symlink(outside, os.path.join(repo, "package.json"))
    n.BuildBundle().run({"repo_path": repo})
    assert "package.json unreadable" in capsys.readouterr().out


def test_build_bundle_prints_when_a_pyproject_toml_was_malformed(tmp_path, capsys):
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n", "pyproject.toml": "not [ valid toml"})
    n.BuildBundle().run({"repo_path": repo})
    assert "other manifests malformed" in capsys.readouterr().out


def test_build_bundle_prints_when_a_go_mod_was_unreadable(tmp_path, capsys):
    outside = tmp_path / "outside.mod"
    outside.write_text("module example.com/app\n\nrequire github.com/x/y v1.0.0\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"docker-compose.yml": "services: {}\n"})
    os.symlink(outside, os.path.join(repo, "go.mod"))
    n.BuildBundle().run({"repo_path": repo})
    assert "other manifests unreadable" in capsys.readouterr().out


def test_build_bundle_prints_when_an_env_file_was_unreadable(tmp_path, capsys):
    outside = tmp_path / "outside.env"
    outside.write_text("STRIPE_SECRET_KEY=sk_live_x\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"docker-compose.yml": "services: {}\n"})
    os.symlink(outside, os.path.join(repo, ".env"))
    n.BuildBundle().run({"repo_path": repo})
    assert "env files unreadable" in capsys.readouterr().out


def test_build_bundle_prints_when_sdk_imports_were_capped(tmp_path, capsys, monkeypatch):
    """coderay-5wu.7. The console line reports an exact count with no sign
    the git-grep line cap actually cut real evidence."""
    from crawl.analyses.architecture import arch_crawl as ac
    repo = _repo(tmp_path, {"docker-compose.yml": "services:\n  api:\n    image: api\n"})
    monkeypatch.setattr(ac, "_sdk_grep", lambda repo, max_lines=ac.SDK_GREP_MAX_LINES:
                         ("a.ts:1: stripe", None, True))
    n.BuildBundle().run({"repo_path": repo})
    assert "capped" in capsys.readouterr().out


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


def test_sent_names_the_files_the_bundle_carried(tmp_path):
    """coderay-3eu: the manifest reads what BuildBundle stored."""
    from crawl.analyses import architecture
    repo = _repo(tmp_path, {"docker-compose.yml": "services:\n  api:\n    image: api\n",
                            ".env": "APP_KEY=1\n", "integrations/stripe/x.js": "", "integrations/slack/y.js": ""})
    shared = {"repo_path": repo}
    n.BuildBundle().run(shared)
    assert architecture.sent(shared) == {"files": [".env", "docker-compose.yml"], "sdk_import_files": [],
                                         "integration_dirs": ["slack", "stripe"]}
