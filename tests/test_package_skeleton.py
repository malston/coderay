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
