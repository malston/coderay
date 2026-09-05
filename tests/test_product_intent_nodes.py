import pathlib

import pytest

import crawl.core.llm as llm_module
from crawl.analyses.product_intent import nodes as n


def _fake_llm(monkeypatch, fn):
    """PainScene and VariantSentence call call_llm directly; the YAML nodes go
    through crawl.core.yaml_call, which resolves call_llm in its own module."""
    monkeypatch.setattr(n, "call_llm", fn)
    monkeypatch.setattr(llm_module, "call_llm", fn)


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = pathlib.Path(tmp_path, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


POSITIONING = """```yaml
competitors:
  - name: "Ours"
    cells:
      - {verdict: "Yes", detail: "d"}
      - {verdict: "Yes", detail: "d"}
      - {verdict: "Yes", detail: "d"}
  - name: "Theirs"
    cells:
      - {verdict: "No", detail: "d"}
      - {verdict: "No", detail: "d"}
      - {verdict: "No", detail: "d"}
dimensions:
  - {name: "A", definition: "a"}
  - {name: "B", definition: "b"}
  - {name: "C", definition: "c"}
sacrifices: ["s"]
gains: ["g"]
why_incumbents_cannot_copy: "because"
```"""

SURPRISES = """```yaml
present:
  - {headline: "h", where: "w", bet: "b"}
absent:
  - {headline: "h", evidence: "e", tradeoff: "t"}
```"""


def test_bundle_keeps_whole_files_and_reports_what_the_budget_dropped(tmp_path):
    """coderay-q2r.47. Upstream concatenated every kept file with no cap. The
    budget caps how many files go in, never how much of each: a truncated
    file reads as a finished one to the model."""
    repo = _tree(tmp_path, {f"src/f{i}.py": f"x = {i}\n" * 20 for i in range(10)})
    bundle, stats = n.bundle(repo, max_chars=800)
    assert stats["included"] < 10 and stats["dropped"] == 10 - stats["included"]
    assert all(block.count("x = ") % 20 == 0 for block in bundle.split("File: ")[1:])
    assert "File: src/f0.py" in bundle
    whole, whole_stats = n.bundle(repo, max_chars=10 ** 6)
    assert whole_stats == {"included": 10, "dropped": 0, "unreadable": 0}


def test_bundle_honours_include_and_exclude_patterns(tmp_path):
    repo = _tree(tmp_path, {"src/a.py": "a\n", "src/gen/b.py": "b\n", "docs2/c.py": "c\n"})
    only_src, _ = n.bundle(repo, include=["src/**"])
    assert "File: src/a.py" in only_src and "docs2/c.py" not in only_src
    no_gen, _ = n.bundle(repo, include=["src/**"], exclude=["**/gen/**"])
    assert "src/gen/b.py" not in no_gen and "File: src/a.py" in no_gen


def test_fetch_repo_refuses_an_empty_bundle_before_any_llm_call(tmp_path):
    """Four paid passes over nothing would otherwise invent a product."""
    repo = _tree(tmp_path, {"src/a.py": "a\n"})
    with pytest.raises(SystemExit, match=r"No source.*nothing/\*\*"):
        n.FetchRepo().run({"repo_path": repo, "include": ["nothing/**"], "exclude": []})


def test_fetch_repo_stores_the_bundle(tmp_path, capsys):
    repo = _tree(tmp_path, {"src/a.py": "a\n"})
    shared = {"repo_path": repo, "include": [], "exclude": []}
    n.FetchRepo().run(shared)
    assert "File: src/a.py" in shared["codebase"]
    assert "1 files" in capsys.readouterr().out


def test_pain_and_variant_fill_the_codebase_and_keep_the_prose(monkeypatch):
    prompts = []
    _fake_llm(monkeypatch, lambda p: prompts.append(p) or "  a scene  ")
    shared = {"codebase": "THE CODE {not a slot}"}
    n.PainScene().run(shared)
    n.VariantSentence().run(shared)
    assert shared["pain"] == "a scene" and shared["variant"] == "a scene"
    assert all("THE CODE {not a slot}" in p for p in prompts)


def test_competitive_positioning_retries_a_competitor_without_a_name(monkeypatch):
    """coderay-q2r.48. The renderer reads c["name"] after the call is paid for."""
    calls = []

    def reply(prompt):
        calls.append(prompt)
        bad = POSITIONING.replace('  - name: "Theirs"\n    cells:', '  - cells:')
        return bad if len(calls) < 3 else POSITIONING

    _fake_llm(monkeypatch, reply)
    shared = {"codebase": "c"}
    n.CompetitivePositioning().run(shared)
    assert len(calls) == 3
    assert [c["name"] for c in shared["positioning"]["competitors"]] == ["Ours", "Theirs"]


def test_competitive_positioning_retries_a_flat_string_cell(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        bad = POSITIONING.replace('- {verdict: "No", detail: "d"}', '- "No"', 1)
        return bad if len(calls) < 2 else POSITIONING

    _fake_llm(monkeypatch, reply)
    shared = {"codebase": "c"}
    n.CompetitivePositioning().run(shared)
    assert len(calls) == 2


def test_surprises_retries_an_item_missing_a_key(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        bad = SURPRISES.replace(', tradeoff: "t"', '')
        return bad if len(calls) < 2 else SURPRISES

    _fake_llm(monkeypatch, reply)
    shared = {"codebase": "c"}
    n.SurprisesAndAbsences().run(shared)
    assert len(calls) == 2
    assert shared["surprises"]["absent"][0]["tradeoff"] == "t"


@pytest.mark.parametrize("name", ["pain-scene.md", "variant-sentence.md",
                                  "competitive-positioning.md", "surprises-and-absences.md"])
def test_every_prompt_loads(name):
    assert "{codebase}" in n.load_prompt(name)


def test_bundle_counts_the_files_it_could_not_read(tmp_path, capsys):
    """A binary or unreadable file used to vanish from the stats, so
    `Crawled 1 files` hid three that were skipped."""
    repo = _tree(tmp_path, {"src/a.py": "a\n"})
    pathlib.Path(repo, "src/b.py").write_bytes(b"\xff\xfe\x00binary")
    bundle, stats = n.bundle(repo)
    assert stats == {"included": 1, "dropped": 0, "unreadable": 1}
    n.FetchRepo().run({"repo_path": repo, "include": [], "exclude": []})
    assert "1 files could not be read" in capsys.readouterr().out


def test_bundle_drop_line_tells_the_user_how_to_steer(tmp_path, capsys, monkeypatch):
    """The budget itself is tested above; this pins the message."""
    monkeypatch.setattr(n, "bundle", lambda *a, **k: ("File: x\n", {"included": 1, "dropped": 5, "unreadable": 0}))
    n.FetchRepo().run({"repo_path": str(tmp_path), "include": [], "exclude": []})
    out = capsys.readouterr().out
    assert "Dropped 5 files" in out and "--include" in out and "--exclude" in out


def test_list_files_walks_directories_in_sorted_order(tmp_path, monkeypatch):
    """Which files fit under the budget must not depend on scandir order, so
    the walk is fed a scrambled order and must still come out sorted."""
    import os
    from crawl.core import files, list_files
    names = ["mid", "zeta", "alpha", "omega", "beta"]
    repo = _tree(tmp_path, {f"{d}/f.py": "x\n" for d in names})
    real_walk = os.walk

    def scrambled(root, **kw):
        for dirpath, dirnames, filenames in real_walk(root, **kw):
            dirnames.sort(key=names.index) if set(dirnames) == set(names) else None
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(files.os, "walk", scrambled)
    rels = [pathlib.Path(p).relative_to(repo).parts[0] for p in list_files(repo)]
    assert rels == sorted(names)


@pytest.mark.parametrize("node", [n.PainScene, n.VariantSentence])
def test_prose_nodes_reject_a_blank_reply(monkeypatch, node):
    """A whitespace reply passed .strip() and rendered an empty blockquote."""
    _fake_llm(monkeypatch, lambda p: "   \n")
    nd = node()
    nd.wait = 0
    with pytest.raises(AssertionError, match="empty"):
        nd.run({"codebase": "c"})


@pytest.mark.parametrize("mutate", [
    lambda y: y.replace('why_incumbents_cannot_copy: "because"', 'why_incumbents_cannot_copy:'),
    lambda y: y.replace('sacrifices: ["s"]', 'sacrifices: "one long string"'),
    lambda y: y.replace('{verdict: "No", detail: "d"}', '{verdict: {a: 1}, detail: "d"}', 1),
    lambda y: y.replace('      - {verdict: "No", detail: "d"}\n', '', 1),          # ragged: 2 cells for 3 dims
    lambda y: y.replace('  - name: "Theirs"\n    cells:\n', '  - name: "Theirs"\n    other:\n'),
    # A fence inside the diagram would close render_markdown's ```mermaid block;
    # parse_yaml's non-greedy fence match cuts the reply there, so it never parses.
    lambda y: y.replace('why_incumbents_cannot_copy: "because"',
                        'why_incumbents_cannot_copy: "because"\ndiagram: "flowchart LR\\n  A\\n```\\n<script>x</script>"'),
])
def test_competitive_positioning_retries_shapes_the_renderer_cannot_take(monkeypatch, mutate):
    """Each of these passed the old normalize and either crashed render.py
    after all four paid calls or rendered garbage silently."""
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return mutate(POSITIONING) if len(calls) < 2 else POSITIONING

    assert mutate(POSITIONING) != POSITIONING
    _fake_llm(monkeypatch, reply)
    shared = {"codebase": "c"}
    n.CompetitivePositioning().run(shared)
    assert len(calls) == 2


def test_competitive_positioning_says_when_no_diagram_came_back(monkeypatch, capsys):
    _fake_llm(monkeypatch, lambda p: POSITIONING)
    n.CompetitivePositioning().run({"codebase": "c"})
    assert "no diagram" in capsys.readouterr().out


@pytest.mark.parametrize("mutate", [
    lambda y: y.replace('  - {headline: "h", where: "w", bet: "b"}', '  - "headline where bet"'),
    lambda y: y.replace('  - {headline: "h", evidence: "e", tradeoff: "t"}', '  []'),
])
def test_surprises_retries_items_that_are_not_objects_or_lists_that_are_empty(monkeypatch, mutate):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return mutate(SURPRISES) if len(calls) < 2 else SURPRISES

    assert mutate(SURPRISES) != SURPRISES
    _fake_llm(monkeypatch, reply)
    shared = {"codebase": "c"}
    n.SurprisesAndAbsences().run(shared)
    assert len(calls) == 2


def test_variant_print_strips_control_characters_and_newlines(monkeypatch, capsys):
    _fake_llm(monkeypatch, lambda p: "ok\x1b[31m\nfake line of output")
    n.VariantSentence().run({"codebase": "c"})
    out = capsys.readouterr().out
    assert "\x1b" not in out and out.count("\n") == 1
    assert "Variant sentence: ok[31m fake line of output..." in out
