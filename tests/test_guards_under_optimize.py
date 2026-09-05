"""coderay-q2r.50. The pre-flight guard in each analysis stops the run before
its first paid call when the crawl found nothing. `python -O` strips assert
statements, so a guard written as one vanishes and the run pays for prompts
over nothing; each guard is a SystemExit, which -O leaves alone."""
import subprocess
import sys

import pytest

CASES = {
    "backend": "from crawl.analyses.backend.nodes import BuildBundle as N",
    "architecture": "from crawl.analyses.architecture.nodes import BuildBundle as N",
    "interfaces": "from crawl.analyses.interfaces.nodes import FindRoutes as N",
    "schema": "from crawl.analyses.schema.nodes import FindSchema as N",
}


@pytest.mark.parametrize("name,imp", sorted(CASES.items()))
def test_the_preflight_guard_survives_python_dash_O(tmp_path, name, imp):
    (tmp_path / "README.md").write_text("nothing here\n")
    code = f"{imp}\nN().run({{'repo_path': {str(tmp_path)!r}}})\nprint('GUARD DID NOT FIRE')"
    proc = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
    assert "GUARD DID NOT FIRE" not in proc.stdout, name
    assert proc.returncode != 0 and ("No " in proc.stderr or "No " in proc.stdout), (name, proc.stderr[-300:])
