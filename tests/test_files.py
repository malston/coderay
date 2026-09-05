import pytest
import os
import sys

import crawl.core  # noqa: F401  (populates sys.modules["crawl.core.files"])
from crawl.core.files import list_files, safe_read

files = sys.modules["crawl.core.files"]


def test_wanted_rejects_credential_shaped_names():
    assert not files._wanted(".env", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)
    assert not files._wanted("id_rsa", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)
    assert not files._wanted("credentials.json", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)
    assert not files._wanted("service-account.json", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)


def test_wanted_rejects_credential_shaped_suffixes():
    assert not files._wanted("foo.pem", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)
    assert not files._wanted("prod.key", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)


def test_wanted_still_accepts_ordinary_source_files():
    assert files._wanted("main.py", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)
    assert files._wanted("Dockerfile", files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES)


def test_list_files_excludes_credential_shaped_files(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----\n")

    files = list_files(str(tmp_path))

    names = {os.path.basename(p) for p in files}
    assert names == {"main.py"}


def test_list_files_excludes_symlink_escaping_the_repo_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.py").write_text("AKIA...\n")
    (repo / "config.yaml").symlink_to(outside / "settings.py")

    files = list_files(str(repo))

    names = {os.path.basename(p) for p in files}
    assert names == {"main.py"}


def test_safe_read_reads_only_max_chars(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 10_000)
    assert safe_read(str(path), max_chars=100) == "x" * 100


def test_safe_read_without_max_chars_reads_whole_file(tmp_path):
    path = tmp_path / "small.txt"
    path.write_text("hello")
    assert safe_read(str(path)) == "hello"


def test_safe_read_returns_none_on_broken_symlink(tmp_path):
    target = tmp_path / "missing.txt"
    link = tmp_path / "link.txt"
    os.symlink(str(target), str(link))
    assert safe_read(str(link)) is None


def test_list_files_skips_broken_symlink_instead_of_crashing(tmp_path):
    (tmp_path / "real.py").write_text("print('hi')")
    os.symlink(str(tmp_path / "missing.py"), str(tmp_path / "dangling.py"))
    files = list_files(str(tmp_path))
    names = {os.path.basename(f) for f in files}
    assert "real.py" in names
    assert "dangling.py" not in names


def test_list_files_skips_a_symlink_that_renames_a_credential_file(tmp_path):
    """coderay-q2r.52. `_wanted` ran on the link's own name, so
    `src/config.py -> ../.env` looked like source and the target was inside
    the repo, and the whole .env was read and sent to the model."""
    import os
    from crawl.core import list_files
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "src" / "real.py").write_text("x = 1\n")
    (repo / "src" / "config.py").symlink_to(repo / ".env")
    (repo / "src" / "alias.py").symlink_to(repo / "src" / "real.py")   # a legitimate symlink stays
    rels = sorted(os.path.relpath(p, repo) for p in list_files(str(repo)))
    assert rels == ["src/alias.py", "src/real.py"]


def test_list_files_matches_extensions_case_insensitively(tmp_path):
    """coderay-q2r.54: older PHP and Java trees carry `.PHP` and `.JAVA`; the
    extension filter reads them as the same language as their lowercase form."""
    (tmp_path / "index.PHP").write_text("<?php\n")
    (tmp_path / "Main.JAVA").write_text("class Main {}\n")
    names = {os.path.basename(p) for p in list_files(str(tmp_path))}
    assert names == {"index.PHP", "Main.JAVA"}


def test_list_files_keeps_r_scripts_in_either_case(tmp_path):
    (tmp_path / "analysis.R").write_text("x <- 1\n")
    (tmp_path / "helpers.r").write_text("y <- 2\n")
    names = {os.path.basename(p) for p in list_files(str(tmp_path))}
    assert names == {"analysis.R", "helpers.r"}


def test_wanted_rejects_credential_shaped_names_in_any_case():
    """The extension match is case-insensitive, so the credential skip has to
    be too, or `credentials.JSON` slips through on the extension alone."""
    for name in ("credentials.JSON", "SECRETS.YML", "token.JSON", "Service-Account.json"):
        assert not files._wanted(name, files.DEFAULT_KEEP_EXT, files.DEFAULT_KEEP_NAMES), name
    assert not files._wanted("server.PEM", files.DEFAULT_KEEP_EXT | {".pem"}, files.DEFAULT_KEEP_NAMES)


def test_list_files_accepts_an_uppercase_keep_ext_override(tmp_path):
    (tmp_path / "analysis.r").write_text("x <- 1\n")
    (tmp_path / "helpers.R").write_text("y <- 2\n")
    names = {os.path.basename(p) for p in list_files(str(tmp_path), keep_ext={".R"})}
    assert names == {"analysis.r", "helpers.R"}


def test_readable_refuses_a_credential_named_target_unless_the_crawler_opts_in(tmp_path):
    """coderay-q2r.56. The name checked is the resolved target's, so a symlink
    cannot rename a credential file into source. The architecture crawler
    reads a real .env on purpose (variable names only) and opts in; the opt-in
    never extends to a symlink."""
    from crawl.core import readable
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "src" / "real.py").write_text("x = 1\n")
    (repo / "src" / "config.py").symlink_to(repo / ".env")
    (repo / "src" / "alias.py").symlink_to(repo / "src" / "real.py")

    assert not readable(repo, repo / ".env")                # a credential file named outright
    assert readable(repo, repo / ".env", credential_names=True)   # unless the crawler reads it on purpose
    assert not readable(repo, repo / "src" / "config.py", credential_names=True)  # a symlink to one never is
    assert readable(repo, repo / "src" / "alias.py")        # a legitimate in-repo symlink
    assert not readable(repo, repo / "src" / "config.py")   # a symlink that renames one


def test_credential_names_cover_every_dotenv_variant_except_the_templates():
    """coderay-q2r.60. The list named .env, .env.local and .env.production, so
    `.env.staging` and `.envrc` were read whole. Every `.env*` is a credential
    file except the two committed templates the crawlers keep on purpose."""
    for name in (".env.staging", ".env.test", ".ENV.Development", ".envrc"):
        assert not files._wanted(name, set(), {name}), name
    for name in (".env.example", ".env.sample"):
        assert files._wanted(name, set(), files.DEFAULT_KEEP_NAMES), name


def test_readable_refuses_a_symlink_to_a_dotenv_variant(tmp_path):
    """coderay-q2r.60. Reproduction from the PR #30 review."""
    from crawl.core import readable
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env.staging").write_text("STAGE=stag3\n")
    (repo / "cfg.ts").symlink_to(repo / ".env.staging")
    assert not readable(repo, repo / "cfg.ts")


def test_dotenv_templates_are_the_keep_names_dotenv_entries():
    """PR #30 review. `_wanted` refuses every `.env*` before it consults
    keep_names, so a template listed in one set and not the other silently
    disagrees. One set derives from the other."""
    assert {n for n in files.DEFAULT_KEEP_NAMES if n.startswith('.env')} == files.DOTENV_TEMPLATES
    for name in files.DOTENV_TEMPLATES:
        assert files._wanted(name, set(), files.DEFAULT_KEEP_NAMES)


# coderay-5wu.23: run_state.json and manifest.json are written whole or not at all.
def test_write_text_atomic_leaves_no_partial_file_when_the_write_is_interrupted(tmp_path, monkeypatch):
    import crawl.core.files as files

    class Interrupted:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def write(self, text): raise KeyboardInterrupt

    monkeypatch.setattr(files.os, "fdopen", lambda fd, *a, **k: (files.os.close(fd), Interrupted())[1])
    target = tmp_path / "run_state.json"
    with pytest.raises(KeyboardInterrupt):
        files.write_text_atomic(str(target), "x" * 10_000)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # the temp file is gone too


def test_write_text_atomic_replaces_the_target_whole(tmp_path):
    from crawl.core.files import write_text_atomic
    target = tmp_path / "manifest.json"
    target.write_text("old", encoding="utf-8")
    assert write_text_atomic(str(target), "new") == str(target)
    assert target.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["manifest.json"]
