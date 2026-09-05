"""coderay-5wu.19: crawl refuses to import with optimisation on (python -O, PYTHONOPTIMIZE);
src/crawl/__init__.py says why. The env var flips the same __debug__, so one path covers both."""
import subprocess
import sys


def test_the_package_refuses_to_import_under_python_dash_O():
    proc = subprocess.run([sys.executable, "-O", "-c", "import crawl"], capture_output=True, text=True)
    assert proc.returncode == 1, proc.stderr[-300:]
    assert "python -O" in proc.stderr and "PYTHONOPTIMIZE" in proc.stderr and "assert" in proc.stderr, proc.stderr[-300:]
    assert "Traceback" not in proc.stderr, proc.stderr[-300:]
