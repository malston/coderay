import os
import pathlib
import subprocess

import pytest

from crawl.analyses.git_history import gitlog as gl


def _repo(tmp_path, commits, dates=None):
    """Build a real git repo: gitlog shells out, so a fixture cannot fake it.
    `dates` pins each commit's author and committer date (ISO strings)."""
    repo = str(tmp_path)
    env = dict(os.environ)
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Tester")
    for i, (subject, writes, removes) in enumerate(commits):
        for rel, text in writes.items():
            p = pathlib.Path(repo, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for rel in removes:
            os.remove(pathlib.Path(repo, rel))
        if dates:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = dates[i]
        run("add", "-A")
        run("commit", "-qm", subject)
    return repo


def _mkdir(p):
    p.mkdir()
    return p


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
    """`went silent` is the signal an abandoned bet leaves behind. The flag
    only fires when the directory's last month is before the repo's last
    month, so the two commits need real, different dates."""
    repo = _repo(tmp_path, [
        ("old work", {"legacy/a.py": "1\n"}, []),
        ("new work", {"current/b.py": "2\n"}, []),
    ], dates=["2019-03-01T12:00:00+00:00", "2020-07-01T12:00:00+00:00"])
    commits = gl.git_log_commits(repo)
    pivots = gl.pivots_summary(commits)
    assert "legacy/  born 2019-03  last active 2019-03  <- went silent" in pivots
    current = [l for l in pivots.splitlines() if l.startswith("current/")]
    assert current == ["current/  born 2020-07  last active 2020-07"]
    heat = gl.heatmap_summary(commits)
    assert "legacy/" in heat and "total 1" in heat


def test_a_record_separator_in_a_subject_cannot_forge_a_commit(tmp_path):
    """coderay-q2r.35. git allows the 0x1e record separator inside a subject,
    so a hostile repo can split one log entry into two and choose the hash
    field of the second. Both parsers keep only 40-hex hashes, and show_diff
    puts --end-of-options before the hash, so a forged one can never be read
    as a git option (--output=<path> is an arbitrary file write)."""
    target = tmp_path.parent / f"{tmp_path.name}-pwned.txt"
    forged = f"cleanup\x1e--output={target}|1600000000|ev|forged"
    repo = _repo(_mkdir(tmp_path / "r"), [
        ("add", {f"f{i}.py": "x\n" for i in range(6)}, []),
        (forged, {}, [f"f{i}.py" for i in range(6)]),
    ])
    hashes = [c["hash"] for c in gl.git_log_commits(repo)]
    hashes += [c["hash"] for c in gl.bulk_changes(repo, "D", min_files=5)]
    assert hashes and all(gl.HEX_HASH.fullmatch(h) for h in hashes), hashes
    assert not target.exists()
    with pytest.raises(subprocess.CalledProcessError):
        gl.show_diff(repo, f"--output={target}")
    assert not target.exists()


def test_bulk_changes_reports_the_full_hash(tmp_path):
    """An abbreviated hash is ambiguous in a large repo and defeats the
    40-hex check; both parsers use %H."""
    repo = _repo(tmp_path, [("add", {f"f{i}.py": "x\n" for i in range(6)}, []),
                            ("rm", {}, [f"f{i}.py" for i in range(6)])])
    assert len(gl.bulk_changes(repo, "D", min_files=5)[0]["hash"]) == 40


@pytest.mark.parametrize("header", [
    'diff --git "a/secrets/\\303\\244pi.pem" "b/secrets/\\303\\244pi.pem"',   # quoted path
    "diff --cc .env",                                                        # merge, combined
    "diff --combined .env",
    "diff --git a/b/deploy.pem b/b/deploy.pem",                              # dir named b/
    "diff --git a/Credentials.JSON b/Credentials.JSON",                      # case-folded (q2r.62)
])
def test_redact_secret_files_recognises_every_header_git_emits(header):
    """coderay-q2r.36. git C-quotes non-ASCII paths, prints merges as
    `diff --cc`, and a/ b/ are prefixes, not a character set."""
    diff = f"commit abc\n{header}\n-SECRET=LEAK\n"
    out = gl.redact_secret_files(diff)
    assert "LEAK" not in out
    assert header in out


def test_redact_secret_files_ignores_header_text_inside_a_body():
    """A removed line that happens to read `-diff --git ...` is body, not a
    header; treating it as one re-emits the rest of the secret."""
    diff = ("diff --git a/.env b/.env\n-A=LEAK1\n"
            "-diff --git a/x b/x\n-B=LEAK2\n"
            "diff --git a/src/a.py b/src/a.py\n+x = 1\n")
    out = gl.redact_secret_files(diff)
    assert "LEAK1" not in out and "LEAK2" not in out
    assert "+x = 1" in out


def test_show_diff_redacts_a_secret_resolved_in_a_merge(tmp_path):
    """Merges print combined diffs (`diff --cc`); landmarks routinely pick the
    merge that closes an era."""
    repo = _repo(tmp_path, [("base", {".env": "K=base\n", "a.py": "1\n"}, [])])
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    run("checkout", "-qb", "side")
    pathlib.Path(repo, ".env").write_text("K=side\n"); run("commit", "-qam", "side")
    run("checkout", "-q", "-")
    pathlib.Path(repo, ".env").write_text("K=main\n"); run("commit", "-qam", "main")
    subprocess.run(["git", "-C", repo, "merge", "side"], capture_output=True)
    pathlib.Path(repo, ".env").write_text("K=MERGE_LEAK\n"); run("add", ".env"); run("commit", "-qm", "merge")
    merge = gl.git_log_commits(repo)[0]
    assert merge["subject"] == "merge"
    diff = gl.show_diff(repo, merge["hash"], max_chars=12_000)
    assert "diff --cc .env" in diff
    assert "MERGE_LEAK" not in diff


@pytest.mark.parametrize("path", [
    "secrets.yml", "config/secrets.yml", "secrets.yaml", "secrets.json",
    ".git-credentials", ".pgpass", "kubeconfig", "client_secret.json",
    "id_ecdsa", "id_dsa",
])
def test_is_secret_path_covers_credential_files_beyond_the_noise_list(path):
    """coderay-q2r.37: the skip list started as crawler noise, not a secrets list."""
    assert gl.is_secret_path(path) is True


def test_repo_root_refuses_a_subdirectory_of_a_repo(tmp_path):
    """coderay-q2r.38. `git -C` walks up to the enclosing .git, so a plain folder
    inside any repo would be analysed as its parent, under the wrong name."""
    repo = _repo(tmp_path, [("first", {"pkg/a.py": "1\n"}, [])])
    assert gl.repo_root(repo) == os.path.realpath(repo)
    with pytest.raises(SystemExit) as e:
        gl.repo_root(os.path.join(repo, "pkg"))
    assert "pkg" in str(e.value) and repo in str(e.value)


def test_is_shallow_tells_a_depth_one_clone_from_a_full_one(tmp_path):
    repo = _repo(_mkdir(tmp_path / "full"), [("first", {"a.py": "1\n"}, []), ("second", {"b.py": "2\n"}, [])])
    clone = str(tmp_path / "shallow")
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", clone], check=True)
    assert gl.is_shallow(repo) is False
    assert gl.is_shallow(clone) is True


def test_unquote_strips_a_prefix_not_a_character_set():
    assert gl._unquote("a/backend/app.py") == "backend/app.py"
    assert gl._unquote('"b/s/\\303\\244.pem"') == "s/\\303\\244.pem"


def test_a_forged_record_with_a_real_blob_hash_cannot_dump_the_blob(tmp_path):
    """coderay-q2r.35, second pass. A 40-hex check alone still let a hostile
    subject forge a record whose hash was a real BLOB (a committed .env, say):
    `git show <blob>` prints it raw with no diff header, so the redactor had
    nothing to anchor on. The record separator is now NUL, which git refuses
    in a message, and show_diff peels its argument to a commit."""
    repo = _repo(_mkdir(tmp_path / "r"), [("add", {".env": "TOKEN=SUPERSECRET\n",
                                                   **{f"f{i}.py": "x\n" for i in range(6)}}, [])])
    blob = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD:.env"], text=True).strip()
    forged = f"cleanup\x1e{blob}|1600000000|Mallory|forged"
    _repo(tmp_path / "r", [(forged, {}, [f"f{i}.py" for i in range(6)] + [".env"])])
    dels = gl.bulk_changes(repo, "D", min_files=5)
    assert [d["author"] for d in dels] == ["Tester"]        # the real record, whole
    assert dels[0]["subject"].startswith("cleanup")
    assert all(gl.HEX_HASH.fullmatch(c["hash"]) for c in gl.git_log_commits(repo))
    with pytest.raises(subprocess.CalledProcessError):
        gl.show_diff(repo, blob)


@pytest.mark.parametrize("head", [
    "cleanup\x1e", "cleanup\x1ebar",
    "\x1e" + "a" * 40 + "|notanumber|x|y",
    "\x1e" + "a" * 40 + "|99999999999999999999|x|y",
])
def test_a_malformed_subject_cannot_crash_the_parsers(tmp_path, head):
    """Before the whole head was validated, these reached str.split or int()
    and aborted the run with a traceback."""
    repo = _repo(tmp_path, [(head, {"a.py": "1\n"}, [])])
    assert len(gl.git_log_commits(repo)) == 1
    assert gl.bulk_changes(repo, "A", min_files=1)[0]["author"] == "Tester"


def test_a_sha256_repository_is_read_like_any_other(tmp_path):
    """git init --object-format=sha256 gives 64-hex hashes; a 40-hex-only
    check dropped every commit and reported an empty history."""
    repo = str(tmp_path)
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    run("init", "-q", "--object-format=sha256")
    run("config", "user.email", "t@example.com"); run("config", "user.name", "T")
    pathlib.Path(repo, "a.py").write_text("1\n"); run("add", "-A"); run("commit", "-qm", "one")
    commits = gl.git_log_commits(repo)
    assert len(commits) == 1 and len(commits[0]["hash"]) == 64
    assert "a.py" in gl.show_diff(repo, commits[0]["hash"])


def test_show_diff_redacts_a_secret_in_a_directory_with_a_space(tmp_path):
    """git never quotes spaces, so `a/config dir/secrets.json` tokenises into
    halves; the path is read whole from the --- / +++ lines as well."""
    repo = _repo(tmp_path, [
        ("add", {"config dir/secrets.json": '{"token": "SUPERSECRET"}\n',
                 **{f"f{i}.py": "x\n" for i in range(6)}}, []),
        ("rm", {}, ["config dir/secrets.json"] + [f"f{i}.py" for i in range(6)]),
    ])
    diff = gl.show_diff(repo, gl.bulk_changes(repo, "D", min_files=5)[0]["hash"], max_chars=12_000)
    assert "SUPERSECRET" not in diff
    assert "config dir/secrets.json" in diff


def test_hunk_paths_recovers_a_path_with_spaces_whole():
    """Every listed secret name is a single token today, so the tokenised
    fallback happens to catch them; this pins the whole-path reading so a
    future name with a space in it is not silently missed."""
    hunk = "a/my secrets.json b/my secrets.json\ndeleted file mode 100644\n@@ -1 +0,0 @@\n-x\n"
    assert "my secrets.json" in gl._hunk_paths("diff --git ", hunk)
    assert "dir with space/.env" in gl._hunk_paths("diff --cc ", "dir with space/.env\nindex 1..2\n")


@pytest.mark.parametrize("head", [
    "nothash|1600000000|a|s", "a" * 40 + "|notanumber|a|s", "a" * 40 + "|16|a", "",
    "A" * 40 + "|16|a|s", "a" * 41 + "|16|a|s",
])
def test_records_drops_a_head_that_does_not_validate(head):
    """Defence in depth behind the NUL separator: no attacker text reaches
    split, int() or fromtimestamp."""
    assert list(gl._records(f"\x00{head}\nfile.py\n")) == []


def test_records_accepts_sha1_and_sha256_heads():
    raw = f"\x00{'a' * 40}|1600000000|Ann|s1\nx.py\n\x00{'b' * 64}|1600000001|Bob|s|2\ny.py\nz.py\n"
    recs = list(gl._records(raw))
    assert [(r[0][:1], r[1], r[2], r[3], r[4]) for r in recs] == [
        ("a", 1600000000, "Ann", "s1", ["x.py"]), ("b", 1600000001, "Bob", "s|2", ["y.py", "z.py"])]


def test_redact_secret_files_reads_the_path_of_a_renamed_secret():
    diff = ("diff --git a/old name.pem b/new name.pem\n"
            "similarity index 90%\nrename from old name.pem\nrename to new name.pem\n"
            "--- a/old name.pem\n+++ b/new name.pem\n@@ -1 +1 @@\n-LEAK\n+LEAK2\n")
    out = gl.redact_secret_files(diff)
    assert "LEAK" not in out
    assert "diff --git a/old name.pem b/new name.pem" in out


def test_show_diff_still_redacts_when_the_user_forces_git_colour(tmp_path, monkeypatch):
    """color.ui=always wraps every header in escape codes, so a line-anchored
    header match found nothing and redaction dropped to zero."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "color.ui")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    repo = _repo(tmp_path, [
        ("add", {".env": "TOKEN=SUPERSECRET\n", **{f"f{i}.py": "x\n" for i in range(6)}}, []),
        ("rm", {}, [".env"] + [f"f{i}.py" for i in range(6)]),
    ])
    diff = gl.show_diff(repo, gl.bulk_changes(repo, "D", min_files=5)[0]["hash"], max_chars=12_000)
    assert "SUPERSECRET" not in diff
    assert "\x1b[" not in diff


def test_repo_root_accepts_a_path_that_differs_only_in_case(tmp_path):
    """macOS APFS is case-insensitive by default; comparing strings refused
    ~/Code/repo for an on-disk ~/code/repo."""
    repo = _repo(_mkdir(tmp_path / "root"), [("first", {"a.py": "1\n"}, [])])
    swapped = str(tmp_path / "ROOT")
    if not os.path.isdir(swapped):
        pytest.skip("case-sensitive filesystem")
    assert gl.repo_root(swapped) == os.path.realpath(repo)


def test_repo_root_explains_a_directory_that_is_not_a_repo(tmp_path):
    with pytest.raises(SystemExit) as e:
        gl.repo_root(str(tmp_path))
    assert "not a git repository" in str(e.value)


@pytest.mark.parametrize("path", [
    "token.json", "credentials.yml", "secret.json", "secrets.toml",
    "prod.tfvars", "terraform.tfstate", "terraform.tfstate.backup", "putty.ppk",
])
def test_is_secret_path_covers_the_second_review_pass(path):
    assert gl.is_secret_path(path) is True


@pytest.mark.parametrize("path", [".ENV", "Credentials.json", "certs/server.PEM", "ID_RSA"])
def test_is_secret_path_is_case_folded_like_the_crawler_rule(path):
    """coderay-q2r.62: a case-sensitive copy of the rule lets a graveyard commit
    deleting `Credentials.json` send the body to the LLM."""
    assert gl.is_secret_path(path) is True


@pytest.mark.parametrize("path", [".env.example", "config/.env.sample", ".ENV.EXAMPLE"])
def test_is_secret_path_leaves_dotenv_templates_alone(path):
    """Templates carry variable names with placeholder values, so their diffs hold no secrets."""
    assert gl.is_secret_path(path) is False
