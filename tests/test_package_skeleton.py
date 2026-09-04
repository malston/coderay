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
