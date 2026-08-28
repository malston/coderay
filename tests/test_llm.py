import pytest

from coderay_utils.llm import parse_yaml


def test_parse_yaml_raises_value_error_on_missing_fence():
    # Must be a real exception, not assert -- assert is stripped under
    # `python -O`, which would silently break yaml_call's retry-on-bad-output
    # contract.
    with pytest.raises(ValueError, match="missing"):
        parse_yaml("no yaml fence here")
