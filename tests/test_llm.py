import pytest

from crack.core.llm import extract_mermaid, parse_yaml


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


def test_extract_mermaid_returns_the_first_fence_when_no_kind_is_asked_for():
    md = "```mermaid\nflowchart LR\n  a --> b\n```\n\n```mermaid\nerDiagram\n  A ||--o{ B : has\n```"
    assert extract_mermaid(md).startswith("flowchart LR")


def test_extract_mermaid_picks_the_diagram_type_it_is_asked_for():
    """The distinguishing input is an ERD that is not the first fence.

    schema's hero renders an erDiagram; a reply opening with a flowchart would
    otherwise put the wrong diagram in the hero with nothing to signal it.
    """
    md = "```mermaid\nflowchart LR\n  a --> b\n```\n\n```mermaid\nerDiagram\n  A ||--o{ B : has\n```"
    assert extract_mermaid(md, "erDiagram").startswith("erDiagram")


def test_extract_mermaid_returns_nothing_when_the_asked_for_type_is_absent():
    """Better an empty hero than someone else's diagram in it."""
    assert extract_mermaid("```mermaid\nflowchart LR\n  a --> b\n```", "erDiagram") == ""
