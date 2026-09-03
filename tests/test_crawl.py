import os
import sys

import crack.core  # noqa: F401  (populates sys.modules["crack.core.crawl"])
from crack.core.crawl import list_files, safe_read

crawl = sys.modules["crack.core.crawl"]


def test_wanted_rejects_credential_shaped_names():
    assert not crawl._wanted(".env", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)
    assert not crawl._wanted("id_rsa", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)
    assert not crawl._wanted("credentials.json", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)
    assert not crawl._wanted("service-account.json", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)


def test_wanted_rejects_credential_shaped_suffixes():
    assert not crawl._wanted("foo.pem", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)
    assert not crawl._wanted("prod.key", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)


def test_wanted_still_accepts_ordinary_source_files():
    assert crawl._wanted("main.py", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)
    assert crawl._wanted("Dockerfile", crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES)


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
    from crack.core import list_files
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
        assert not crawl._wanted(name, crawl.DEFAULT_KEEP_EXT, crawl.DEFAULT_KEEP_NAMES), name
    assert not crawl._wanted("server.PEM", crawl.DEFAULT_KEEP_EXT | {".pem"}, crawl.DEFAULT_KEEP_NAMES)


def test_list_files_accepts_an_uppercase_keep_ext_override(tmp_path):
    (tmp_path / "analysis.r").write_text("x <- 1\n")
    (tmp_path / "helpers.R").write_text("y <- 2\n")
    names = {os.path.basename(p) for p in list_files(str(tmp_path), keep_ext={".R"})}
    assert names == {"analysis.r", "helpers.R"}


def test_readable_refuses_only_a_symlink_whose_target_is_credential_named(tmp_path):
    """coderay-q2r.56. The crawlers that pick files by their own name still
    read a real .env on purpose (architecture, for variable names), so the
    target-name check applies to symlinks alone."""
    from crack.core import readable
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / ".env").write_text("SECRET=1\n")
    (repo / "src" / "real.py").write_text("x = 1\n")
    (repo / "src" / "config.py").symlink_to(repo / ".env")
    (repo / "src" / "alias.py").symlink_to(repo / "src" / "real.py")

    assert readable(repo, repo / ".env")                    # a real credential file, read on purpose
    assert readable(repo, repo / "src" / "alias.py")        # a legitimate in-repo symlink
    assert not readable(repo, repo / "src" / "config.py")   # a symlink that renames one
