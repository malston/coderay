import os

from utils.crawl import list_files, safe_read


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
