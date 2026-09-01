import os
import subprocess
import sys

import pytest

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "fixtures", "toy_repo")

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")),
    reason="no API key set; smoke test needs a real LLM call",
)

def test_crack_tour_runs_end_to_end(tmp_path):
    out_dir = str(tmp_path / "tour-output")
    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "tour", FIXTURE_REPO, "--out", out_dir],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert os.path.isfile(os.path.join(out_dir, "index.md"))
    assert os.path.isfile(os.path.join(out_dir, "index.html"))
