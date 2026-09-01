import argparse

import pytest

from crack.analyses.tour import run


def test_run_exits_with_message_when_repo_path_is_not_a_directory(tmp_path):
    args = argparse.Namespace(repo_path=str(tmp_path / "missing"), out=None,
                               instructions="beginner-tutorial", dry_run=False)
    with pytest.raises(SystemExit, match="is not a directory"):
        run(args)
