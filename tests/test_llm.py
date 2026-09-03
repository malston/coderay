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


def test_render_and_llm_share_one_extract_mermaid():
    """Two copies drifted once already: only llm's learned the `kind` argument,
    so a caller reaching for render's got the first fence regardless."""
    from crack.core import llm, render

    assert render.extract_mermaid is llm.extract_mermaid
    reply = "```mermaid\nflowchart LR\n  a-->b\n```\n```mermaid\nerDiagram\n  USER\n```"
    assert render.extract_mermaid(reply, "erDiagram").startswith("erDiagram")


@pytest.mark.parametrize("call,bad,good", [
    ("json_call", '```json\n[1, 2, 3]\n```', '```json\n[{"name": "era"}]\n```'),
    ("yaml_call", '```yaml\n- 1\n- 2\n```', '```yaml\n- name: era\n```'),
])
def test_a_reply_of_the_wrong_shape_retries_rather_than_escaping(monkeypatch, call, bad, good):
    """coderay-q2r.33. normalize() sees whatever the model returned.

    `"name" in 1` raises TypeError, which the original tuple did not catch, so
    all four retries were skipped and the caller's own except never matched.
    That is the exact shape NameEras hits: a list of scalars where it expects a
    list of era objects. The good reply on the third attempt is what proves the
    retries actually ran rather than the error being swallowed.
    """
    import crack.core.llm as llm_module

    calls = []

    def fake(prompt):
        calls.append(prompt)
        return bad if len(calls) < 3 else good

    monkeypatch.setattr(llm_module, "call_llm", fake)

    def normalize(data):
        assert "name" in data[0]        # TypeError while data[0] is an int
        return data

    assert getattr(llm_module, call)(prompt="p", normalize=normalize) == [{"name": "era"}]
    assert len(calls) == 3, "the wrong-shaped replies must have been retried"


@pytest.mark.parametrize("call", ["json_call", "yaml_call"])
def test_a_transport_error_is_not_swallowed_by_the_retry_loop(monkeypatch, call):
    """Transport errors belong to the node's own max_retries, not here."""
    import crack.core.llm as llm_module

    def boom(prompt):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(llm_module, "call_llm", boom)
    with pytest.raises(RuntimeError, match="connection reset"):
        getattr(llm_module, call)(prompt="p", normalize=lambda d: d)


def test_parse_json_survives_a_fenced_block_inside_a_string_value():
    """raw_decode, not a closing-fence regex: a nested ``` inside a string value
    would truncate a regex-based parse at the wrong place."""
    from crack.core.llm import parse_json

    reply = '```json\n{"note": "see ```mermaid\\ngraph LR\\n``` above", "n": 2}\n```'
    assert parse_json(reply) == {"note": "see ```mermaid\ngraph LR\n``` above", "n": 2}
