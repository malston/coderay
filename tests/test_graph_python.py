from workflow.graph.languages.python import imports


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
