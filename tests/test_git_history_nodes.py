import json
import pathlib
import subprocess

import pytest

import crack.core.llm as llm_module
from crack.analyses.git_history import nodes as n


def _repo(tmp_path, commits):
    repo = str(tmp_path)
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Tester")
    for subject, writes, removes in commits:
        for rel, text in writes.items():
            p = pathlib.Path(repo, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for rel in removes:
            (pathlib.Path(repo, rel)).unlink()
        run("add", "-A")
        run("commit", "-qm", subject)
    return repo


def _fake_llm(monkeypatch, fn):
    """The LLM nodes reach the model two ways: call_llm directly (Graveyard) and
    crack.core.json_call (NameEras, ProfileEras), which resolves call_llm in its
    own module. Patch both or a json_call path hits the real API."""
    monkeypatch.setattr(n, "call_llm", fn)
    monkeypatch.setattr(llm_module, "call_llm", fn)


ERAS = [{"name": "Early", "start": "2019-01", "end": "2019-12",
         "description": "d", "turning_point": "t"}]
PROFILE = {"cast": {"narrative": "c", "people": []}, "mood": {"narrative": "m", "patterns": []}}


def test_fetch_history_populates_the_commit_lists(tmp_path):
    repo = _repo(tmp_path, [("first", {"a.py": "1\n"}, []), ("second", {"b.py": "2\n"}, [])])
    shared = {"repo_path": repo}
    n.FetchHistory().run(shared)
    assert len(shared["commits"]) == 2
    assert [c["subject"] for c in shared["commits_asc"]] == ["first", "second"]


def test_name_eras_stores_the_parsed_eras(monkeypatch, tmp_path):
    _fake_llm(monkeypatch, lambda p: "```json\n" + json.dumps(ERAS) + "\n```")
    shared = {"commits": [{"month": "2019-01", "files": ["a.py"]}],
              "bulk_dels": [], "bulk_adds": []}
    n.NameEras().run(shared)
    assert shared["eras"] == ERAS


def test_name_eras_retries_an_era_missing_a_required_field(monkeypatch, tmp_path):
    """A flaky model drops a field on a large prompt; the whole page is built
    from these keys, so an era without `start` would break the era windows."""
    calls = []

    def reply(prompt):
        calls.append(prompt)
        if len(calls) < 3:
            return '```json\n[{"name": "Early", "description": "d"}]\n```'
        return "```json\n" + json.dumps(ERAS) + "\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"commits": [{"month": "2019-01", "files": ["a.py"]}],
              "bulk_dels": [], "bulk_adds": []}
    n.NameEras().run(shared)
    assert len(calls) == 3
    assert shared["eras"] == ERAS


def test_name_eras_unwraps_a_model_that_nests_the_list(monkeypatch):
    """Some models answer {"eras": [...]} rather than a bare list."""
    _fake_llm(monkeypatch, lambda p: '```json\n' + json.dumps({"eras": ERAS}) + '\n```')
    shared = {"commits": [{"month": "2019-01", "files": ["a.py"]}],
              "bulk_dels": [], "bulk_adds": []}
    n.NameEras().run(shared)
    assert shared["eras"] == ERAS


def test_name_eras_survives_a_reply_that_is_a_list_of_scalars(monkeypatch):
    """coderay-q2r.33. `"name" in 42` raises TypeError inside normalize.

    Before the catch tuple covered it this escaped json_call's retries AND the
    node's, killing the run on a bad reply the retry exists to absorb.
    """
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "```json\n[1, 2, 3]\n```" if len(calls) < 3 else "```json\n" + json.dumps(ERAS) + "\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"commits": [{"month": "2019-01", "files": ["a.py"]}],
              "bulk_dels": [], "bulk_adds": []}
    n.NameEras().run(shared)
    assert len(calls) == 3
    assert shared["eras"] == ERAS


def test_profile_eras_carries_prior_summaries_into_the_next_prompt(monkeypatch, tmp_path):
    """Eras run in sequence, not as a batch, so each prompt can contrast with
    the ones before it. A batch node would lose that."""
    repo = _repo(tmp_path, [("c", {"a.py": "1\n"}, [])])
    prompts = []
    _fake_llm(monkeypatch, lambda p: prompts.append(p) or ("```json\n" + json.dumps(PROFILE) + "\n```"))
    two = ERAS + [{"name": "Later", "start": "2020-01", "end": "2020-12",
                   "description": "d2", "turning_point": "t2"}]
    # A real hash: ProfileEras runs `git show` on its landmark commits, so a
    # made-up one fails in git rather than in the code under test.
    from crack.analyses.git_history import gitlog as gl
    real = gl.git_log_commits(repo)[0]
    shared = {"repo_path": repo,
              "commits_asc": [dict(real, month="2019-06")],
              "eras": two}
    n.ProfileEras().run(shared)
    assert len(shared["profiles"]) == 2
    assert "(this is the first era)" in prompts[0]
    assert "Era 1" in prompts[1]


def test_graveyard_skips_a_vendored_deletion(monkeypatch, tmp_path):
    """Deleting node_modules dwarfs every real deletion by raw count, so ranking
    by size alone buries the actual graves."""
    vendored = {f"node_modules/pkg/f{i}.js": "x\n" for i in range(30)}
    real = {f"core/feature/f{i}.py": "x\n" for i in range(10)}
    repo = _repo(tmp_path, [("add", {**vendored, **real}, []),
                            ("drop vendor", {}, list(vendored)),
                            ("drop feature", {}, list(real))])
    from crack.analyses.git_history import gitlog as gl
    _fake_llm(monkeypatch, lambda p: "entry")
    shared = {"repo_path": repo, "eras": ERAS,
              "bulk_dels": gl.bulk_changes(repo, "D", min_files=5),
              "grave_min_files": 8, "max_graves": 6}
    n.Graveyard().run(shared)
    scopes = [g["commit"]["scope"] for g in shared["graves"]]
    assert any("core" in s for s in scopes)
    assert not any("node_modules" in s for s in scopes)


def test_graveyard_honours_max_graves(monkeypatch, tmp_path):
    areas = {f"area{a}/f{i}.py": "x\n" for a in range(4) for i in range(10)}
    repo = _repo(tmp_path, [("add", areas, [])] +
                 [(f"drop {a}", {}, [f"area{a}/f{i}.py" for i in range(10)]) for a in range(4)])
    from crack.analyses.git_history import gitlog as gl
    _fake_llm(monkeypatch, lambda p: "entry")
    shared = {"repo_path": repo, "eras": ERAS,
              "bulk_dels": gl.bulk_changes(repo, "D", min_files=5),
              "grave_min_files": 8, "max_graves": 2}
    n.Graveyard().run(shared)
    assert len(shared["graves"]) == 2


@pytest.mark.parametrize("name", ["name-eras.md", "profile-era.md", "graveyard-entry.md"])
def test_every_prompt_loads(name):
    assert n.load_prompt(name).strip()
