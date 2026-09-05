import argparse
import os

import pytest

from crawl.analyses import ANALYSES, architecture


def test_architecture_is_registered():
    assert ANALYSES["architecture"] is architecture
    assert architecture.NAME == "architecture"


def test_architecture_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(architecture, attr), attr


def test_architecture_declares_the_card_family_contract():
    assert len(architecture.SECTIONS) == 3
    assert [s.key for s in architecture.SECTIONS] == [
        "inventory_md", "techstack_md", "trace_md"]
    assert [s.number for s in architecture.SECTIONS] == ["01", "02", "03"]
    assert [s.width for s in architecture.SECTIONS] == [380, 420, 460]
    assert architecture.THEME.title_suffix == "architecture"


def test_architecture_raises_more_output_tokens():
    assert architecture.ENV_DEFAULTS == {"LLM_MAX_OUTPUT_TOKENS": "32768"}


def test_add_arguments_adds_no_flags_of_its_own():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    before = {a.dest for a in parser._actions}
    architecture.add_arguments(parser)
    assert {a.dest for a in parser._actions} == before


def test_init_shared_carries_the_repo_path():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    assert architecture.init_shared(args) == {"repo_path": "/tmp/toy_repo"}


def test_build_flow_starts_at_build_bundle():
    from crawl.analyses.architecture.nodes import BuildBundle
    assert isinstance(architecture.build_flow().start_node, BuildBundle)


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        architecture.run(argparse.Namespace(repo_path=str(f), out=None))


def test_overview_spec_names_the_three_sections_and_counts_the_nodes():
    spec = architecture.overview_spec({
        "repo_path": "/tmp/toy_repo",
        "shape_verdict": "A gateway in front of four services.",
        "inventory_md": "### 1 · Gateway\nbody\n\n### 2 · Auth\nbody\n",
    })
    assert spec["name"] == "toy_repo"
    assert [t for t, _ in spec["sections"]] == ["The inventory", "Tech stack", "The trace"]
    assert "2 nodes on the map" in spec["facts"]
    assert "A gateway in front of four services." in spec["facts"]


def test_overview_spec_counts_only_headers_that_start_a_line():
    """A `###` in the middle of a line is not a node card.

    The regex anchors to the start of a line and knows nothing about fences, so
    a `### foo` at the start of a line inside a fenced block IS counted. The
    distinguishing input is the mid-line `###` below: drop the anchor and the
    count reads three nodes here, not two.
    """
    spec = architecture.overview_spec({
        "repo_path": "/tmp/toy_repo",
        "inventory_md": ("### 1 · Gateway\nbody\n\n"
                         "```\ncomment ### not a header\n```\n\n"
                         "### 2 · Auth\nbody\n"),
    })
    assert "2 nodes on the map" in spec["facts"]


def test_overview_spec_name_matches_the_name_the_page_is_rendered_with(tmp_path, monkeypatch):
    """The overview prompt and the page title must name the same repo.

    run_analysis hands the renderer repo_name_of(args.repo_path) as the page
    title. "." is the case that exposes a divergence from a naive basename.
    """
    from crawl.core.runner import repo_name_of

    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    spec = architecture.overview_spec({"repo_path": ".", "inventory_md": ""})
    assert spec["name"] == repo_name_of(".") == "toy_repo"
    assert spec["name"] != os.path.basename(".")


def test_the_hero_diagram_is_escaped_before_it_reaches_the_page():
    """The diagram is LLM-authored from repo content, so it is untrusted."""
    html = architecture._hero_prefix({"arch_diagram": "graph LR;\n</pre><script>alert(1)</script>"})
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


def test_the_hero_diagram_block_is_omitted_when_no_graph_was_parsed():
    assert architecture._hero_prefix({"arch_diagram": ""}) == ""
    assert architecture._hero_prefix({}) == ""


def test_the_subtitle_falls_back_from_the_welcome_to_the_verdict_to_a_default():
    assert architecture._subtitle(
        {"overview": {"welcome": "NATS runs four services."},
         "shape_verdict": "unused"}) == "NATS runs four services."
    assert architecture._subtitle(
        {"shape_verdict": "A gateway in front of four services."}
    ) == "A gateway in front of four services."
    assert architecture._subtitle({}) == "A multi-service architecture, read three ways."


def test_the_footer_reports_the_crawl_stats():
    footer = architecture._footer({"arch_stats": {"config_files": 9, "deps": 42,
                                                  "integrations": 6}})
    assert "9 config files" in footer
    assert "42 dependencies" in footer
    assert "6 integrations" in footer


def test_the_footer_says_when_sdk_import_evidence_was_unavailable():
    """coderay-q2r.15: a report built on configuration alone must say so."""
    stats = {"config_files": 9, "deps": 42, "integrations": 6, "sdk_lines": 0,
             "sdk_unavailable": "not a git repository"}
    footer = architecture._footer({"arch_stats": stats})
    assert "SDK import evidence unavailable (not a git repository)" in footer
    assert "unavailable" not in architecture._footer({"arch_stats": {**stats, "sdk_unavailable": None}})


def test_the_footer_says_when_sdk_import_evidence_was_capped():
    """coderay-5wu.7. sdk_lines == the cap reads as a precise count with
    nothing telling the reader the list was cut."""
    stats = {"config_files": 9, "deps": 42, "integrations": 6, "sdk_lines": 400,
             "sdk_capped": True}
    footer = architecture._footer({"arch_stats": stats})
    assert "capped" in footer
    assert "capped" not in architecture._footer({"arch_stats": {**stats, "sdk_capped": False}})


def test_the_footer_escapes_the_unavailable_note():
    """Defence in depth: the crawler never passes git text through, and the
    footer escapes what it is handed anyway, since it lands in HTML."""
    footer = architecture._footer({"arch_stats": {"sdk_unavailable": "<script>x</script>"}})
    assert "<script>" not in footer and "&lt;script&gt;" in footer
