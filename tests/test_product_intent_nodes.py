import pathlib

import pytest

import crack.core.llm as llm_module
from crack.analyses.product_intent import nodes as n


def _fake_llm(monkeypatch, fn):
    """PainScene and VariantSentence call call_llm directly; the YAML nodes go
    through crack.core.yaml_call, which resolves call_llm in its own module."""
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
  - name: "Theirs"
    cells:
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
    assert whole_stats == {"included": 10, "dropped": 0}


def test_bundle_honours_include_and_exclude_patterns(tmp_path):
    repo = _tree(tmp_path, {"src/a.py": "a\n", "src/gen/b.py": "b\n", "docs2/c.py": "c\n"})
    only_src, _ = n.bundle(repo, include=["src/**"])
    assert "File: src/a.py" in only_src and "docs2/c.py" not in only_src
    no_gen, _ = n.bundle(repo, include=["src/**"], exclude=["**/gen/**"])
    assert "src/gen/b.py" not in no_gen and "File: src/a.py" in no_gen


def test_fetch_repo_refuses_an_empty_bundle_before_any_llm_call(tmp_path):
    """Four paid passes over nothing would otherwise invent a product."""
    repo = _tree(tmp_path, {"src/a.py": "a\n"})
    with pytest.raises(AssertionError, match="No source"):
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
        bad = POSITIONING.replace('- {verdict: "No", detail: "d"}', '- "No"')
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
