import json
import os
import pathlib
import subprocess

import pytest

import crawl.core.llm as llm_module
from crawl.analyses.git_history import nodes as n


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


def _mkdir(p):
    p.mkdir()
    return p


def _fake_llm(monkeypatch, fn):
    """The LLM nodes reach the model two ways: call_llm directly (Graveyard) and
    crawl.core.json_call (NameEras, ProfileEras), which resolves call_llm in its
    own module. Patch both or a json_call path hits the real API."""
    monkeypatch.setattr(n, "call_llm", fn)
    monkeypatch.setattr(llm_module, "call_llm", fn)


ERAS = [{"name": "Early", "start": "2019-01", "end": "2019-12",
         "description": "d", "turning_point": "t"}]
PROFILE = {"cast": {"narrative": "c", "contributors": []}, "mood": {"narrative": "m", "patterns": []}}


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
    from crawl.analyses.git_history import gitlog as gl
    real = gl.git_log_commits(repo)[0]
    shared = {"repo_path": repo,
              "commits_asc": [dict(real, month="2019-06"), dict(real, month="2020-06")],
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
    from crawl.analyses.git_history import gitlog as gl
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
    from crawl.analyses.git_history import gitlog as gl
    _fake_llm(monkeypatch, lambda p: "entry")
    shared = {"repo_path": repo, "eras": ERAS,
              "bulk_dels": gl.bulk_changes(repo, "D", min_files=5),
              "grave_min_files": 8, "max_graves": 2}
    n.Graveyard().run(shared)
    assert len(shared["graves"]) == 2


def test_is_noise_deletion_checks_skip_dirs_by_forward_slash_not_os_sep(monkeypatch):
    """coderay-q2r.44. Git paths are always forward-slash; splitting on the
    platform's `os.sep` mis-detects the skip-list on Windows (backslash).
    Patching the platform separator must not change the answer."""
    monkeypatch.setattr(os, "sep", "\\")
    change = {"files": [f"node_modules/pkg/f{i}.js" for i in range(10)]}
    assert n._is_noise_deletion(change) is True


@pytest.mark.parametrize("name", ["name-eras.md", "profile-era.md", "graveyard-entry.md"])
def test_every_prompt_loads(name):
    assert n.load_prompt(name).strip()


def test_fetch_history_warns_when_the_clone_is_shallow(tmp_path, capsys):
    """coderay-q2r.38. A depth-1 clone prints `Crawled 1 commits` and every
    downstream call splits one commit into eras; the run should say so."""
    repo = _repo(_mkdir(tmp_path / "full"), [("first", {"a.py": "1\n"}, []), ("second", {"b.py": "2\n"}, [])])
    clone = str(tmp_path / "shallow")
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", clone], check=True)
    n.FetchHistory().run({"repo_path": clone})
    out = capsys.readouterr().out
    assert "shallow" in out.lower()
    n.FetchHistory().run({"repo_path": repo})
    assert "shallow" not in capsys.readouterr().out.lower()


SHARED_ONE_COMMIT = {"commits": [{"month": "2019-01", "files": ["a.py"]}],
                     "bulk_dels": [], "bulk_adds": []}


@pytest.mark.parametrize("bad", [
    [{"name": "E", "start": "Jan 2019", "end": "Dec 2019", "description": "d", "turning_point": "t"}],
    [{"name": "E", "start": "2019-01", "end": None, "description": "d", "turning_point": "t"}],
    [{"name": "E", "start": "2019", "end": "2019-12", "description": "d", "turning_point": "t"}],
])
def test_name_eras_retries_an_era_whose_dates_are_not_year_month(monkeypatch, bad):
    """coderay-q2r.39. era_commits string-compares YYYY-MM; any other form
    either selects nothing (an empty era is then profiled) or raises TypeError
    outside json_call, burning the node retries on a deterministic error."""
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "```json\n" + json.dumps(bad if len(calls) < 3 else ERAS) + "\n```"

    _fake_llm(monkeypatch, reply)
    shared = dict(SHARED_ONE_COMMIT)
    n.NameEras().run(shared)
    assert len(calls) == 3
    assert shared["eras"] == ERAS


def test_profile_eras_skips_an_era_that_matches_no_commits(monkeypatch, tmp_path, capsys):
    """coderay-q2r.39. Otherwise the model is asked to profile a window of
    `(no commits)` placeholders and its invention renders as a normal card."""
    repo = _repo(tmp_path, [("c", {"a.py": "1\n"}, [])])
    from crawl.analyses.git_history import gitlog as gl
    real = gl.git_log_commits(repo)[0]
    calls = []
    _fake_llm(monkeypatch, lambda p: calls.append(p) or ("```json\n" + json.dumps(PROFILE) + "\n```"))
    empty = {"name": "Ghost", "start": "2030-01", "end": "2030-12", "description": "d", "turning_point": "t"}
    shared = {"repo_path": repo, "commits_asc": [dict(real, month="2019-06")], "eras": ERAS + [empty]}
    n.ProfileEras().run(shared)
    assert len(calls) == 1
    assert [p["era"]["name"] for p in shared["profiles"]] == ["Early"]
    assert "Ghost" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [
    {"cast": "one founder", "mood": PROFILE["mood"]},
    {"cast": PROFILE["cast"], "mood": "cheerful"},
    {"cast": {"narrative": "c"}, "mood": PROFILE["mood"]},          # object, no contributors
])
def test_profile_eras_retries_a_profile_whose_cast_or_mood_has_the_wrong_shape(monkeypatch, tmp_path, capsys, bad):
    """coderay-q2r.39. `"cast" in result` is true for {"cast": "text"}; the
    .get() on it then failed outside json_call and re-ran every era."""
    repo = _repo(tmp_path, [("c", {"a.py": "1\n"}, [])])
    from crawl.analyses.git_history import gitlog as gl
    real = gl.git_log_commits(repo)[0]
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "```json\n" + json.dumps(bad if len(calls) < 3 else PROFILE) + "\n```"

    _fake_llm(monkeypatch, reply)
    shared = {"repo_path": repo, "commits_asc": [dict(real, month="2019-06")], "eras": ERAS}
    n.ProfileEras().run(shared)
    assert len(calls) == 3
    assert shared["profiles"][0]["profile"] == PROFILE
    # Retried inside json_call (varied tail), not by re-running the whole node.
    assert capsys.readouterr().out.count("Profiling era") == 1


def test_graveyard_with_max_graves_zero_digs_nothing(monkeypatch, tmp_path):
    """coderay-q2r.40: the cap was checked after the append, so 0 meant 1."""
    files = {f"area/f{i}.py": "x\n" for i in range(10)}
    repo = _repo(tmp_path, [("add", files, []), ("drop", {}, list(files))])
    from crawl.analyses.git_history import gitlog as gl
    calls = []
    _fake_llm(monkeypatch, lambda p: calls.append(p) or "entry")
    shared = {"repo_path": repo, "eras": ERAS,
              "bulk_dels": gl.bulk_changes(repo, "D", min_files=5),
              "grave_min_files": 8, "max_graves": 0}
    n.Graveyard().run(shared)
    assert shared["graves"] == [] and calls == []


def test_era_for_returns_none_for_a_month_no_era_covers():
    """coderay-q2r.40. Falling through to the last era attributed a 2010
    deletion to the 2020 era, in the card and in the prompt."""
    eras = [{"start": "2019-01", "end": "2019-12"}, {"start": "2020-01", "end": "2020-12"}]
    assert n._era_for("2019-06", eras) is eras[0]
    assert n._era_for("2020-12", eras) is eras[1]
    assert n._era_for("2010-01", eras) is None
    assert n._era_for("2021-01", eras) is None


def test_profile_eras_records_the_commits_and_diffs_it_sent(monkeypatch, tmp_path):
    """coderay-3eu: no files leave in this analysis; commit subjects and diffs do."""
    repo = _repo(tmp_path, [(f"c{i}", {"a.py": f"{i}\n"}, []) for i in range(5)])
    _fake_llm(monkeypatch, lambda p: "```json\n" + json.dumps(PROFILE) + "\n```")
    from crawl.analyses.git_history import gitlog as gl
    asc = [dict(c, month="2019-06") for c in gl.commits_ascending(gl.git_log_commits(repo))]
    shared = {"repo_path": repo, "commits_asc": asc, "eras": ERAS, "profile_max_commits": 2}
    n.ProfileEras().run(shared)
    # the sample went as subject lines, not the whole window
    sampled, _ = gl.sample_commits(asc, 2)
    assert 0 < len(sampled) < len(asc)
    assert shared["profiles"][0]["commits_sent"] == [c["hash"] for c in sampled]
    assert set(shared["profiles"][0]["diffs_sent"]) <= {c["hash"] for c in asc}
    assert len(shared["profiles"][0]["diffs_sent"]) == len(set(shared["profiles"][0]["diffs_sent"]))


def test_sent_gathers_the_commits_listed_and_the_diffs_shown():
    from crawl.analyses.git_history import sent
    shared = {"commits": [{"hash": "a"}, {"hash": "b"}, {"hash": "c"}, {"hash": "d"}],
              "survey_commits_sent": ["d"],
              "profiles": [{"commits_sent": ["a", "b"], "diffs_sent": ["a"]},
                           {"commits_sent": ["b", "c"], "diffs_sent": ["c"]}],
              "graves": [{"commit": {"hash": "b"}}]}
    assert sent(shared) == {"commits_logged": 4, "commits_listed": ["a", "b", "c", "d"], "diffs": ["a", "b", "c"]}


def test_name_eras_records_the_bulk_change_commits_whose_subjects_it_sent(monkeypatch):
    """coderay-3eu: the survey prompt carries a verbatim line per bulk change
    (hash, date, count, scope, subject), up to twenty of each kind."""
    _fake_llm(monkeypatch, lambda p: "```json\n" + json.dumps(ERAS) + "\n```")
    big = {"hash": "d" * 40, "date": "2019-02-01", "count": 12, "scope": "core", "subject": "drop", "month": "2019-02"}
    add = {"hash": "a" * 40, "date": "2019-01-01", "count": 30, "scope": "core", "subject": "add", "month": "2019-01"}
    shared = {"commits": [{"month": "2019-01", "files": ["a.py"]}], "bulk_dels": [big], "bulk_adds": [add]}
    n.NameEras().run(shared)
    assert shared["survey_commits_sent"] == ["d" * 40, "a" * 40]
