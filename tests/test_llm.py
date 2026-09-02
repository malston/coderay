import pytest

from crack.core.llm import parse_yaml


def test_parse_yaml_raises_value_error_on_missing_fence():
    # Must be a real exception, not assert -- assert is stripped under
    # `python -O`, which would silently break yaml_call's retry-on-bad-output
    # contract.
    with pytest.raises(ValueError, match="missing"):
        parse_yaml("no yaml fence here")


def test_extract_mermaid_returns_the_first_block_body():
    from crack.core import extract_mermaid
    md = "intro\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\ntail\n"
    assert extract_mermaid(md) == "flowchart LR\n  a --> b"

def test_extract_mermaid_returns_empty_when_absent():
    from crack.core import extract_mermaid
    assert extract_mermaid("no diagram here") == ""
    assert extract_mermaid("") == ""
    assert extract_mermaid(None) == ""

def test_extract_mermaid_ignores_a_non_mermaid_fence():
    from crack.core import extract_mermaid
    assert extract_mermaid("```python\nx = 1\n```") == ""
