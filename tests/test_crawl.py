import sys

import utils  # noqa: F401  (populates sys.modules["utils.crawl"])

crawl = sys.modules["utils.crawl"]


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

    files = crawl.list_files(str(tmp_path))

    names = {p.split("/")[-1] for p in files}
    assert names == {"main.py"}


def test_list_files_excludes_symlink_escaping_the_repo_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "credentials").write_text("AKIA...\n")
    (repo / "config.yaml").symlink_to(outside / "credentials")

    files = crawl.list_files(str(repo))

    names = {p.split("/")[-1] for p in files}
    assert names == {"main.py"}
