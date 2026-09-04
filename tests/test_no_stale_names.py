"""The package is `crawl`; nothing tracked still calls it by the old name.

The sweep covers every tracked file except the beads store, the handoff
prompts, and the lockfile uv regenerates. The only tolerated mentions are the
sibling port source, whose package keeps the old name: its directory name,
any line that discusses the sibling, and the lines that deliberately import it.
"""
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLD_NAME = re.compile(r"(?<![a-z])crack(?![a-z])", re.IGNORECASE)
SIBLING = "Crack-Any-Codebase-with-AI"
SKIP_PREFIXES = (".beads/", ".prompts/")
SKIP_FILES = {"uv.lock", "tests/test_no_stale_names.py"}
SIBLING_IMPORT = re.compile(r"_crack\b|^\s*(import crack\b|from crack\.)")
ALLOWED_LINES = {
    "scripts/regen_golden.py": SIBLING_IMPORT,
    "docs/superpowers/plans/2026-09-01-backend-analysis-port.md": SIBLING_IMPORT,
}


def tracked_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    for rel in out.decode().split("\0"):
        if rel and not rel.startswith(SKIP_PREFIXES) and rel not in SKIP_FILES:
            yield rel


def stale_lines(rel):
    allowed = ALLOWED_LINES.get(rel)
    try:
        text = (ROOT / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []
    return [f"{rel}:{n}: {line.strip()}"
            for n, line in enumerate(text.splitlines(), 1)
            if OLD_NAME.search(line)
            and SIBLING not in line
            and "sibling" not in line
            and not (allowed and allowed.search(line))]


def test_no_tracked_path_carries_the_old_name():
    assert [rel for rel in tracked_files() if OLD_NAME.search(rel)] == []


def test_no_tracked_file_mentions_the_old_name():
    hits = [hit for rel in tracked_files() for hit in stale_lines(rel)]
    assert hits == [], f"{len(hits)} stale mentions:\n" + "\n".join(hits[:40])


def test_ordinary_words_containing_the_old_name_are_not_stale():
    assert OLD_NAME.search("a firecracker cracked the crackdown") is None
    for stale in ("crack.core", "src/crack/", "CRACK_TEST", "Crack tour", '"crack"'):
        assert OLD_NAME.search(stale), stale
