"""coderay-q2r.50. The pre-flight guard in each analysis stops the run before
its first paid call when the crawl found nothing. `python -O` strips assert
statements, so a guard written as one vanishes and the run pays for prompts
over nothing; each guard is a SystemExit, which -O leaves alone."""
import subprocess
import sys

import pytest

CASES = {
    "backend": ("from crawl.analyses.backend.nodes import BuildBundle as N", "No backend source found"),
    "architecture": ("from crawl.analyses.architecture.nodes import BuildBundle as N", "No architecture sources found"),
    "interfaces": ("from crawl.analyses.interfaces.nodes import FindRoutes as N", "No route/surface files found"),
    "schema": ("from crawl.analyses.schema.nodes import FindSchema as N", "No schema file found"),
}


@pytest.mark.parametrize("name,case", sorted(CASES.items()))
def test_the_preflight_guard_survives_python_dash_O(tmp_path, name, case):
    """The guard's own message, and no traceback: an uncaught SystemExit(str)
    prints only the string, while a crash before the guard (an import error, a
    missing file) prints a traceback and would otherwise pass for a fired guard."""
    imp, message = case
    (tmp_path / "README.md").write_text("nothing here\n")
    code = (f"{imp}\nif __debug__: print('NOT OPTIMIZED')\n"
            f"N().run({{'repo_path': {str(tmp_path)!r}}})\nprint('GUARD DID NOT FIRE')")
    proc = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
    assert "NOT OPTIMIZED" not in proc.stdout and "GUARD DID NOT FIRE" not in proc.stdout, name
    assert proc.returncode == 1, (name, proc.stderr[-300:])
    assert message in proc.stderr and "Traceback" not in proc.stderr, (name, proc.stderr[-300:])
