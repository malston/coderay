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

def test_every_registered_analysis_ships_its_package_data():
    import pathlib
    import tomllib
    from crawl.analyses import ANALYSES
    root = pathlib.Path(__file__).parent.parent
    cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    packages = cfg["tool"]["setuptools"]["packages"]
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
    """run_analysis writes run_state.json on failure minus INPUT_KEYS, so an
    analysis without the declaration would dump its whole source bundle."""
    from crawl.analyses import ANALYSES
    for name, analysis in ANALYSES.items():
        if name == "tour":
            continue
        assert isinstance(analysis.INPUT_KEYS, frozenset) and analysis.INPUT_KEYS, name


def test_the_tree_sitter_range_admits_only_cores_that_ship_query_cursor():
    """Every extractor imports QueryCursor from tree_sitter, which core 0.25
    added; the Go grammar the lock resolves (0.25) is language ABI 15, which
    only core 0.25 loads. A range that admits 0.23 or 0.24 installs from the
    wheel and fails on the first import (coderay-5wu.16)."""
    import pathlib
    import tomllib
    from packaging.requirements import Requirement
    from packaging.version import Version
    root = pathlib.Path(__file__).parent.parent
    cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    core = [Requirement(d) for d in cfg["project"]["dependencies"] if Requirement(d).name == "tree-sitter"]
    assert len(core) == 1, core
    spec = core[0].specifier
    assert Version("0.24.0") not in spec and Version("0.23.0") not in spec
    assert Version("0.25.0") in spec
