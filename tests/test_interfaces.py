import argparse
import os

import pytest

from crawl.analyses import ANALYSES, interfaces


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
    assert seq.md_note is interfaces._sequence_note


def test_the_sequence_markdown_note_reaches_the_page():
    """coderay-5wu.10. render_markdown never calls `cards`, so the q2r.25
    ungrounded note and the 5wu.1 fallback note previously reached the HTML
    page only; a reader of index.md saw a diagram with no marker at all."""
    from crawl.core.render import render_markdown

    ungrounded = {"sequence_grounded": False, "sequence_endpoint": "POST /x",
                  "sequence_md": "```mermaid\nsequenceDiagram\n  a->>b: x\n```"}
    out = render_markdown(interfaces, "repo", ungrounded)
    assert "No handler source was read" in out

    fallback = {"sequence_grounded": True, "sequence_endpoint": "POST /x",
                "sequence_fallback": "app/urls.py", "sequence_dropped": [],
                "sequence_md": "```mermaid\nsequenceDiagram\n  a->>b: x\n```"}
    out = render_markdown(interfaces, "repo", fallback)
    assert "The model named no source files" in out


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
    from crawl.analyses.interfaces.nodes import FindRoutes
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
    from crawl.core.runner import repo_name_of
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


def test_the_footer_says_how_many_route_files_were_actually_read():
    """coderay-q2r.24. Files dropped by the size cap were counted as read.

    The distinguishing input is a run where the two differ; when they agree the
    footer reads the same either way.
    """
    footer = interfaces._footer({"route_files": ["a.rb", "b.py", "c.ts"],
                                 "route_files_read": ["a.rb"],
                                 "group_names": ["G (1)"]})
    assert "Read from 1 route files of 3 found" in footer


def test_the_footer_stays_quiet_when_every_route_file_was_read():
    footer = interfaces._footer({"route_files": ["a.rb"], "route_files_read": ["a.rb"],
                                 "group_names": []})
    assert "of 1 found" not in footer
    assert "Read from 1 route files" in footer


def test_the_sequence_card_says_when_the_diagram_had_no_handler_source():
    """coderay-q2r.25. An ungrounded diagram renders identically to a real one.

    The model writes it from the route list and invents its file:line refs, so
    the page has to say so -- stdout scrolls past during a multi-minute run.
    """
    shared = {"sequence_endpoint": "POST /api/book", "sequence_grounded": False}
    html = interfaces._sequence_cards(shared, "```mermaid\nsequenceDiagram\n  a->>b: x\n```")
    assert "No handler source was read" in html
    assert html, "an ungrounded diagram must still render a card carrying the warning"


def test_the_sequence_card_carries_no_warning_on_a_grounded_run():
    shared = {"sequence_endpoint": "POST /api/book", "sequence_grounded": True}
    html = interfaces._sequence_cards(shared, "The write commits here.")
    assert "No handler source" not in html
    assert "The write commits here." in html
    assert "not the files the model named" not in html and "not found" not in html


def test_the_sequence_card_says_when_the_diagram_came_from_the_fallback_file():
    """coderay-5wu.1. A valid pick whose files all miss falls back to the
    largest route file; sequence_grounded is True because source exists, so the
    card was titled with the model's endpoint over unrelated source with no
    marker. The card names the file it was drawn from and the files it was not."""
    shared = {"sequence_endpoint": "POST /api/book", "sequence_grounded": True,
              "sequence_fallback": "app/urls.py",
              "sequence_dropped": ["api/book.py", "<b>x</b>.py"]}
    html = interfaces._sequence_cards(shared, "The write commits here.")
    assert "Drawn from <code>app/urls.py</code>, not the files the model named" in html
    assert "api/book.py" in html and "&lt;b&gt;x&lt;/b&gt;.py" in html and "<b>x</b>" not in html
    assert "none of which could be read" in html and "do not exist" not in html


def test_the_sequence_card_says_when_some_named_files_were_not_read():
    """`read_files` leaves a path out for five reasons (missing, empty, past
    the file cap, over the size budget, refused), so the card says "not read",
    which is true of all five, never "not found"."""
    shared = {"sequence_endpoint": "POST /api/a", "sequence_grounded": True,
              "sequence_fallback": None, "sequence_dropped": ["pages/api/missing.ts"]}
    html = interfaces._sequence_cards(shared, "Body.")
    assert "1 of the files the model named was not read" in html
    assert "pages/api/missing.ts" in html
    assert "not found" not in html and "do not exist" not in html


def test_the_sequence_card_says_when_several_named_files_were_not_read():
    """The plural arm of the not-read note: two or more dropped files, no
    fallback (from the /code-review of PR 45, noted on coderay-5wu.10)."""
    shared = {"sequence_endpoint": "POST /api/a", "sequence_grounded": True,
              "sequence_fallback": None, "sequence_dropped": ["pages/api/a.ts", "pages/api/b.ts"]}
    html = interfaces._sequence_cards(shared, "Body.")
    assert "2 of the files the model named were not read" in html
    assert "pages/api/a.ts" in html and "pages/api/b.ts" in html


def test_the_sequence_card_says_when_the_model_named_no_source_files():
    """Both an unusable pick and a pick with an endpoint but no files leave
    nothing to read; one wording covers both without contradicting the title."""
    for endpoint in ("app/urls.py", "POST /api/book"):
        shared = {"sequence_endpoint": endpoint, "sequence_grounded": True,
                  "sequence_fallback": "app/urls.py", "sequence_dropped": []}
        html = interfaces._sequence_cards(shared, "Body.")
        assert "The model named no source files" in html and "<code>app/urls.py</code>" in html
        assert "unusable" not in html


def test_the_sequence_card_keeps_a_dropped_path_with_underscores_literal():
    """Dropped names sit in code spans, so `__init__.py` is not markdown emphasis."""
    for shared in ({"sequence_grounded": True, "sequence_fallback": None, "sequence_dropped": ["api/__init__.py"]},
                   {"sequence_grounded": True, "sequence_fallback": "app/urls.py", "sequence_dropped": ["api/__init__.py"]}):
        html = interfaces._sequence_cards(shared, "Body.")
        assert "<code>api/__init__.py</code>" in html and "<strong>init" not in html


def test_the_sequence_card_survives_a_backtick_in_a_file_name():
    shared = {"sequence_grounded": True, "sequence_fallback": "we`ird.py", "sequence_dropped": ["a`b.py"]}
    html = interfaces._sequence_cards(shared, "Body.")
    assert "<code>we`ird.py</code>" in html and "<code>a`b.py</code>" in html


def test_the_sequence_card_escapes_the_fallback_path():
    """The fallback file name comes from the target repo's own file names."""
    for dropped in ([], ["a.py"]):
        shared = {"sequence_grounded": True, "sequence_fallback": "app/<img src=x onerror=alert(1)>.py",
                  "sequence_dropped": dropped}
        html = interfaces._sequence_cards(shared, "Body.")
        assert "<img" not in html and "&lt;img" in html


def test_the_ungrounded_note_wins_over_the_dropped_files_note():
    shared = {"sequence_grounded": False, "sequence_fallback": None, "sequence_dropped": ["nope.py"]}
    html = interfaces._sequence_cards(shared, "Body.")
    assert "No handler source" in html and "not read" not in html


def test_the_source_note_survives_a_diagram_only_reply():
    """A reply that is a fence and nothing else strips to an empty body; the
    card must still render so the note is not lost while the diagram shows."""
    shared = {"sequence_endpoint": "POST /api/a", "sequence_grounded": True,
              "sequence_fallback": "app/urls.py", "sequence_dropped": ["gone.py"]}
    html = interfaces._sequence_cards(shared, "```mermaid\nsequenceDiagram\n  a->>b: x\n```")
    assert "Drawn from" in html
