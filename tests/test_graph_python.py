import crack.analyses.tour.graph.languages.python as python_module
from crack.analyses.tour.graph.languages.python import imports


def test_imports_resolves_dotted_module_to_file():
    text = "from pkg.helpers import do_thing\n"
    selected = {"pkg/helpers.py", "pkg/__init__.py", "main.py"}
    assert imports("main.py", text, selected) == ["pkg/helpers.py"]


def test_imports_resolves_package_init():
    text = "import pkg.sub\n"
    selected = {"pkg/sub/__init__.py", "main.py"}
    assert imports("main.py", text, selected) == ["pkg/sub/__init__.py"]


def test_imports_drops_unresolvable_module():
    text = "import numpy\n"  # not in selected_files -- third-party, not in this repo's tour
    selected = {"main.py"}
    assert imports("main.py", text, selected) == []


def test_imports_returns_empty_list_for_file_with_no_imports():
    assert imports("main.py", "x = 1\n", {"main.py"}) == []


def test_imports_drops_ambiguous_module_with_two_candidates():
    text = "import pkg.sub\n"  # could be pkg/sub.py or pkg/sub/__init__.py -- ambiguous
    selected = {"pkg/sub.py", "pkg/sub/__init__.py", "main.py"}
    assert imports("main.py", text, selected) == []


def test_imports_drops_relative_import_rather_than_misresolving_as_absolute():
    # `from .helpers import x` has no `dotted_name` at the import_from_statement's
    # module_name field (it's a `relative_import` node) -- the query never
    # matches it, so this is a safe miss, never a wrong edge, even when a
    # same-named top-level file exists.
    text = "from .helpers import x\n"
    selected = {"helpers.py", "pkg/main.py"}
    assert imports("pkg/main.py", text, selected) == []


def test_imports_uses_platform_separator_for_module_path(monkeypatch):
    monkeypatch.setattr(python_module.os, "sep", "\\")
    text = "import pkg.sub\n"
    selected = {"pkg\\sub.py"}
    assert imports("main.py", text, selected) == ["pkg\\sub.py"]
