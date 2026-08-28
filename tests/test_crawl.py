import os
import sys

import coderay_utils  # noqa: F401  (populates sys.modules["coderay_utils.crawl"])
from coderay_utils.crawl import list_files, safe_read

crawl = sys.modules["coderay_utils.crawl"]


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
    (outside / "credentials").write_text("AKIA...\n")
    (repo / "config.yaml").symlink_to(outside / "credentials")

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
