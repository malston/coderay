import crawl
import crawl.core
import crawl.analyses
import crawl.analyses.tour

def test_crawl_package_is_importable():
    assert crawl is not None

def test_crawl_subpackages_are_importable():
    assert crawl.core is not None
    assert crawl.analyses is not None
    assert crawl.analyses.tour is not None

def test_every_registered_analysis_is_documented():
    import pathlib
    from crawl.analyses import ANALYSES
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    for name in ANALYSES:
        assert f"crawl {name}" in readme, f"README.md does not document `crawl {name}`"

def _pyproject():
    import pathlib
    import tomllib
    root = pathlib.Path(__file__).parent.parent
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_every_registered_analysis_ships_its_package_data():
    from crawl.analyses import ANALYSES
    packages = _pyproject()["tool"]["setuptools"]["packages"]
    for name in ANALYSES:
        pkg = f"crawl.analyses.{name.replace('-', '_')}"
        assert pkg in packages, f"{pkg} missing from [tool.setuptools] packages"


def test_the_file_walker_module_does_not_share_the_package_name():
    import importlib
    import pytest
    importlib.import_module("crawl.core.files")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("crawl.core.crawl")


def test_every_runner_analysis_declares_the_input_keys_its_failure_dump_leaves_out():
    """The failure dump writes run_state.json minus INPUT_KEYS (run_analysis for
    the card and bespoke analyses, the tour's own run()), so an analysis without
    the declaration would dump its whole source bundle."""
    from crawl.analyses import ANALYSES
    for name, analysis in ANALYSES.items():
        assert isinstance(analysis.INPUT_KEYS, frozenset) and analysis.INPUT_KEYS, name


def test_the_tree_sitter_floor_is_the_core_that_ships_query_cursor():
    """The shared capture_texts scaffold imports QueryCursor from tree_sitter,
    which core 0.25 added. A floor below 0.25 installs from the wheel and
    fails on the first import (coderay-5wu.16)."""
    from packaging.requirements import Requirement
    from packaging.version import Version
    reqs = [Requirement(d) for d in _pyproject()["project"]["dependencies"]]
    core = [r for r in reqs if r.name == "tree-sitter"]
    assert len(core) == 1, core
    floors = [s for s in core[0].specifier if s.operator == ">="]
    assert len(floors) == 1, str(core[0].specifier)
    assert Version(floors[0].version) >= Version("0.25")


def test_the_python_floor_is_at_least_the_release_that_ships_tomllib():
    """These tests read pyproject.toml through tomllib, stdlib from 3.11; a
    floor that admits 3.10 claims an interpreter the suite cannot run on
    (coderay-5wu.22)."""
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    floors = [s for s in SpecifierSet(_pyproject()["project"]["requires-python"]) if s.operator == ">="]
    assert len(floors) == 1, floors
    assert Version(floors[0].version) >= Version("3.11")


def test_every_analysis_says_what_it_sent():
    """manifest.json records which repo content reached the model (coderay-3eu);
    an analysis without `sent` would write a manifest that says nothing."""
    from crawl.analyses import ANALYSES
    for name, analysis in ANALYSES.items():
        assert callable(getattr(analysis, "sent", None)), name
