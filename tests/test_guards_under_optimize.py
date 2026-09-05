"""coderay-5wu.19 (Mark's call, 2026-09-04). The package relies on assert
statements: the shape checks in every normalize() raise AssertionError, which
drives the json_call and yaml_call retries, and the post-call output checks
do the same. `python -O` strips all of them, so a wrong-shaped model reply
would pass straight through instead of retrying. Rather than convert about
fifty asserts by hand, the package refuses to import under -O. The four
pre-flight guards stay SystemExit (coderay-q2r.50), which needs no -O test
now that the interpreter never gets that far."""
import subprocess
import sys


def _run(*flags):
    return subprocess.run([sys.executable, *flags, "-c", "import crawl; print('imported')"],
                          capture_output=True, text=True)


def test_the_package_refuses_to_import_under_python_dash_O():
    proc = _run("-O")
    assert "imported" not in proc.stdout
    assert proc.returncode == 1, proc.stderr[-300:]
    assert "python -O" in proc.stderr and "assert" in proc.stderr, proc.stderr[-300:]
    assert "Traceback" not in proc.stderr, proc.stderr[-300:]


def test_the_package_imports_normally_without_dash_O():
    proc = _run()
    assert proc.returncode == 0 and "imported" in proc.stdout, proc.stderr[-300:]
