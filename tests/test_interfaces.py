import argparse
import os

import pytest

from crack.analyses import ANALYSES, interfaces


def test_interfaces_is_registered():
    assert ANALYSES["interfaces"] is interfaces
    assert interfaces.NAME == "interfaces"


def test_interfaces_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(interfaces, attr), attr


def test_interfaces_declares_the_card_family_contract():
    assert len(interfaces.SECTIONS) == 4
    assert [s.key for s in interfaces.SECTIONS] == [
        "groups_md", "tour_md", "flows_md", "sequence_md"]
    assert [s.number for s in interfaces.SECTIONS] == ["01", "02", "03", "04"]
    assert [s.width for s in interfaces.SECTIONS] == [380, 380, 440, 560]
    assert interfaces.THEME.title_suffix == "interfaces"


def test_the_tour_section_is_omitted_when_the_model_wrote_no_tour():
    """The only section of the four that disappears rather than rendering empty."""
    tour = next(s for s in interfaces.SECTIONS if s.key == "tour_md")
    assert tour.when_empty == "omit"
    assert [s.when_empty for s in interfaces.SECTIONS if s.key != "tour_md"] == \
        ["always", "always", "always"]


def test_the_sequence_section_builds_its_own_card_and_prefix():
    seq = next(s for s in interfaces.SECTIONS if s.key == "sequence_md")
    assert seq.prefix is interfaces._sequence_prefix
    assert seq.cards is interfaces._sequence_cards


def test_interfaces_raises_more_output_tokens():
    assert interfaces.ENV_DEFAULTS == {"LLM_MAX_OUTPUT_TOKENS": "32768"}


def test_add_arguments_adds_no_flags_of_its_own():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    before = {a.dest for a in parser._actions}
    interfaces.add_arguments(parser)
    assert {a.dest for a in parser._actions} == before


def test_init_shared_carries_the_repo_path():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    assert interfaces.init_shared(args) == {"repo_path": "/tmp/toy_repo"}


def test_build_flow_starts_at_find_routes():
    from crack.analyses.interfaces.nodes import FindRoutes
    assert isinstance(interfaces.build_flow().start_node, FindRoutes)


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        interfaces.run(argparse.Namespace(repo_path=str(f), out=None))


def test_overview_spec_names_the_four_sections():
    spec = interfaces.overview_spec({
        "repo_path": "/tmp/toy_repo", "opener": "A booking API.",
        "group_names": ["Booking (12)", "Auth (4)"],
        "sequence_endpoint": "POST /api/book",
    })
    assert spec["name"] == "toy_repo"
    assert [t for t, _ in spec["sections"]] == [
        "Feature menu", "The tour", "Action flows", "Endpoint sequence"]
    assert "2 feature groups" in spec["facts"]
    assert "POST /api/book" in spec["facts"]


def test_overview_spec_name_matches_the_name_the_page_is_rendered_with(tmp_path, monkeypatch):
    from crack.core.runner import repo_name_of
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    spec = interfaces.overview_spec({"repo_path": "."})
    assert spec["name"] == repo_name_of(".") == "toy_repo"
    assert spec["name"] != os.path.basename(".")


def test_the_hero_chart_sizes_each_group_against_the_biggest():
    html = interfaces._hero_prefix({"group_names": ["Booking (12 endpoints)", "Auth (3)"]})
    assert "12 endpoints across 2 feature groups" not in html  # 12 + 3 = 15 total
    assert "15 endpoints across 2 feature groups" in html
    assert 'style="width:100%">12<' in html
    assert 'style="width:25%">3<' in html


def test_the_hero_chart_gives_a_tiny_group_a_visible_bar():
    """A group with one endpoint against a hundred would round to a 1% sliver."""
    html = interfaces._hero_prefix({"group_names": ["Big (100)", "Tiny (1)"]})
    assert 'style="width:7%">1<' in html


def test_the_hero_chart_escapes_the_group_names_it_is_handed():
    """Group names are parsed straight out of LLM output."""
    html = interfaces._hero_prefix({"group_names": ["<script>alert(1)</script> (3)"]})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_hero_chart_is_omitted_when_no_group_carries_a_count():
    assert interfaces._hero_prefix({"group_names": ["Booking", "Auth"]}) == ""
    assert interfaces._hero_prefix({}) == ""


def test_the_sequence_prefix_escapes_the_diagram_it_extracts():
    html = interfaces._sequence_prefix(
        {"sequence_md": "```mermaid\nsequenceDiagram\n</pre><script>alert(1)</script>\n```"})
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


def test_the_sequence_card_drops_the_fence_and_escapes_its_header():
    """The card body must not repeat the diagram the prefix already drew."""
    shared = {"sequence_endpoint": "POST /api/<script>alert(1)</script>"}
    body = "```mermaid\nsequenceDiagram\n  a->>b: hi\n```\n\nThe write commits here."
    html = interfaces._sequence_cards(shared, body)
    assert "sequenceDiagram" not in html
    assert "The write commits here." in html
    assert "<script>" not in html


def test_the_sequence_card_is_omitted_when_the_body_is_only_a_diagram():
    body = "```mermaid\nsequenceDiagram\n  a->>b: hi\n```"
    assert interfaces._sequence_cards({"sequence_endpoint": "POST /x"}, body) == ""


def test_the_footer_counts_the_route_files_and_the_groups():
    footer = interfaces._footer({"route_files": ["a.rb", "b.py"], "group_names": ["G (1)"]})
    assert "2 route files" in footer
    assert "1 feature groups" in footer
