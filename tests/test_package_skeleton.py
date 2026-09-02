import crack
import crack.core
import crack.analyses
import crack.analyses.tour

def test_crack_package_is_importable():
    assert crack is not None

def test_crack_subpackages_are_importable():
    assert crack.core is not None
    assert crack.analyses is not None
    assert crack.analyses.tour is not None

def test_every_registered_analysis_is_documented():
    import pathlib
    from crack.analyses import ANALYSES
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    for name in ANALYSES:
        assert f"crack {name}" in readme, f"README.md does not document `crack {name}`"

def test_every_registered_analysis_ships_its_package_data():
    import pathlib
    import tomllib
    from crack.analyses import ANALYSES
    root = pathlib.Path(__file__).parent.parent
    cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    packages = cfg["tool"]["setuptools"]["packages"]
    for name in ANALYSES:
        pkg = f"crack.analyses.{name.replace('-', '_')}"
        assert pkg in packages, f"{pkg} missing from [tool.setuptools] packages"
