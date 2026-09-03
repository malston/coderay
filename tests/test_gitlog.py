import os
import pathlib
import subprocess

import pytest

from crack.analyses.git_history import gitlog as gl


def _repo(tmp_path, commits):
    """Build a real git repo: gitlog shells out, so a fixture cannot fake it."""
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
            os.remove(pathlib.Path(repo, rel))
        run("add", "-A")
        run("commit", "-qm", subject)
    return repo


@pytest.mark.parametrize("path", [
    ".env", ".env.production", ".env.local", "config/.env.staging",
    "deploy.pem", "certs/server.key", "keys/bundle.p12", "terraform.tfvars",
    "credentials.json", "service-account.json", "id_rsa",
])
def test_is_secret_path_covers_the_crawler_skip_sets(path):
    assert gl.is_secret_path(path) is True


@pytest.mark.parametrize("path", [
    "src/main.py", "README.md", "environment.ts", "keyboard.js",
    "docs/env-setup.md", "src/keys.py",
])
def test_is_secret_path_leaves_ordinary_source_alone(path):
    """`environment.ts` and `keyboard.js` start with env/key substrings without
    being credential files; matching on a substring rather than the basename
    rules would eat them."""
    assert gl.is_secret_path(path) is False


def test_show_diff_omits_credential_contents_but_keeps_the_evidence(tmp_path):
    """coderay-q2r.34. The graveyard reads bulk deletions, and deleting a
    committed secret is an ordinary reason a file gets deleted.

    That a .env was removed is signal the analysis should report, so the path
    and the stat line stay; only the body goes.
    """
    src = {f"src{i}.py": f"x = {i}\n" for i in range(9)}
    repo = _repo(tmp_path, [
        ("add everything", {**src,
                            ".env.production": "STRIPE_SECRET_KEY=sk_live_LEAK\n",
                            "deploy.pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowLEAK\n"}, []),
        ("remove the legacy stack", {}, list(src) + [".env.production", "deploy.pem"]),
    ])
    grave = gl.bulk_changes(repo, "D", min_files=5)[0]
    diff = gl.show_diff(repo, grave["hash"], max_chars=12_000, stat=True)

    assert "sk_live_LEAK" not in diff
    assert "MIIEowLEAK" not in diff
    assert ".env.production" in diff          # the deletion is still reported
    assert "deploy.pem" in diff
    assert "x = 0" in diff                    # ordinary source still readable


def test_redact_secret_files_leaves_a_diff_with_no_secrets_untouched():
    """The filter must not rewrite a diff it has no business in."""
    diff = ("commit abc\n---\n src/a.py | 1 +\n\n"
            "diff --git a/src/a.py b/src/a.py\n+x = 1\n")
    assert gl.redact_secret_files(diff) == diff


def test_redact_secret_files_survives_a_stat_only_diff():
    assert gl.redact_secret_files("commit abc\n---\n a | 1 +\n") == "commit abc\n---\n a | 1 +\n"


def test_git_log_commits_reads_hash_month_author_subject_and_files(tmp_path):
    repo = _repo(tmp_path, [("first", {"a.py": "1\n"}, []),
                            ("second", {"b/c.py": "2\n"}, [])])
    commits = gl.git_log_commits(repo)
    assert [c["subject"] for c in commits] == ["second", "first"]   # git log is newest-first
    assert commits[0]["files"] == ["b/c.py"]
    assert commits[0]["author"] == "Tester"
    assert len(commits[0]["hash"]) == 40


def test_commits_ascending_reverses_into_story_order(tmp_path):
    repo = _repo(tmp_path, [("first", {"a.py": "1\n"}, []), ("second", {"b.py": "2\n"}, [])])
    commits = gl.git_log_commits(repo)
    assert [c["subject"] for c in gl.commits_ascending(commits)] == ["first", "second"]


@pytest.mark.parametrize("files,expected", [
    (["core/server/services/members/a.py", "core/server/services/members/b.py"], "core/server"),
    (["core/a.py", "web/b.py"], ""),
    (["a.py"], ""),
    ([], ""),
])
def test_scope_of_caps_the_shared_prefix_at_the_depth_limit(files, expected):
    """The depth cap is the point: without it a deep shared prefix produces a
    label too long to read, and the first case would return the full
    services/members path rather than core/server."""
    assert gl.scope_of(files) == expected


def test_bulk_changes_lists_only_the_deleted_files(tmp_path):
    """--diff-filter=D restricts which PATHS are listed, not just which commits,
    so the file list is exactly the deletion."""
    repo = _repo(tmp_path, [
        ("add", {f"f{i}.py": "x\n" for i in range(6)}, []),
        ("mixed", {"kept.py": "new\n"}, [f"f{i}.py" for i in range(6)]),
    ])
    dels = gl.bulk_changes(repo, "D", min_files=5)
    assert len(dels) == 1
    assert sorted(dels[0]["files"]) == [f"f{i}.py" for i in range(6)]
    assert "kept.py" not in dels[0]["files"]
    assert dels[0]["count"] == 6


def test_bulk_changes_ignores_a_deletion_below_the_threshold(tmp_path):
    repo = _repo(tmp_path, [("add", {f"f{i}.py": "x\n" for i in range(6)}, []),
                            ("small", {}, ["f0.py", "f1.py"])])
    assert gl.bulk_changes(repo, "D", min_files=5) == []


def test_sample_commits_keeps_the_first_and_last(tmp_path):
    """An evenly sampled slice must still span the era, or the model reads a
    truncated arc as the whole story."""
    commits = [{"month": f"2020-{i:02d}", "subject": f"c{i}"} for i in range(1, 13)]
    sampled, was_sampled = gl.sample_commits(commits, 5)
    assert was_sampled is True
    assert len(sampled) <= 6
    assert sampled[0]["subject"] == "c1"
    assert sampled[-1]["subject"] == "c12"


def test_sample_commits_leaves_a_short_era_whole():
    commits = [{"month": "2020-01", "subject": "a"}, {"month": "2020-02", "subject": "b"}]
    sampled, was_sampled = gl.sample_commits(commits, 5)
    assert sampled == commits
    assert was_sampled is False


def test_era_commits_selects_an_inclusive_month_window():
    asc = [{"month": m} for m in ("2019-12", "2020-01", "2020-06", "2020-12", "2021-01")]
    assert gl.era_commits(asc, "2020-01", "2020-12") == [
        {"month": "2020-01"}, {"month": "2020-06"}, {"month": "2020-12"}]


def test_landmarks_returns_five_labelled_slots(tmp_path):
    era = [{"month": f"2020-{i:02d}", "subject": f"c{i}", "files": ["a.py"], "hash": f"h{i}"}
           for i in range(1, 10)]
    marks = gl.landmarks(era)
    assert [label for label, _ in marks] == ["opening", "early", "mid", "late", "closing"]
    assert marks[0][1]["subject"] == "c1"
    assert marks[-1][1]["subject"] == "c9"


def test_landmarks_of_an_empty_era_is_empty():
    assert gl.landmarks([]) == []


def test_heatmap_and_pivots_flag_a_directory_that_went_silent(tmp_path):
    """`went silent` is the signal an abandoned bet leaves behind."""
    repo = _repo(tmp_path, [
        ("old work", {"legacy/a.py": "1\n"}, []),
        ("new work", {"current/b.py": "2\n"}, []),
    ])
    commits = gl.git_log_commits(repo)
    pivots = gl.pivots_summary(commits)
    assert "legacy/" in pivots
    heat = gl.heatmap_summary(commits)
    assert "legacy/" in heat and "total 1" in heat
