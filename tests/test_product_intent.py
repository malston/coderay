import argparse
import os

import pytest

from crawl.analyses import ANALYSES, product_intent


def test_product_intent_is_registered_under_its_hyphenated_name():
    assert ANALYSES["product-intent"] is product_intent
    assert product_intent.NAME == "product-intent"


def test_product_intent_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(product_intent, attr), attr


def test_product_intent_brings_its_own_renderer_instead_of_the_card_contract():
    assert callable(product_intent.render_html)
    assert callable(product_intent.render_markdown)
    assert not hasattr(product_intent, "SECTIONS")
    assert not hasattr(product_intent, "THEME")


def test_product_intent_does_not_raise_the_output_token_ceiling():
    assert product_intent.ENV_DEFAULTS == {}


def test_add_arguments_adds_repeatable_include_and_exclude():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    product_intent.add_arguments(parser)
    args = parser.parse_args(["/tmp/repo", "--include", "src/**", "--include", "go.mod",
                              "--exclude", "**/*_test.go"])
    assert args.include == ["src/**", "go.mod"]
    assert args.exclude == ["**/*_test.go"]
    assert parser.parse_args(["/tmp/repo"]).include == []


def test_init_shared_carries_the_repo_path_and_the_filters():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None,
                              include=["src/**"], exclude=["**/gen/**"])
    assert product_intent.init_shared(args) == {
        "repo_path": "/tmp/toy_repo", "include": ["src/**"], "exclude": ["**/gen/**"]}


def test_init_shared_tolerates_an_args_without_the_filters():
    shared = product_intent.init_shared(argparse.Namespace(repo_path="/tmp/toy_repo", out=None))
    assert shared["include"] == [] and shared["exclude"] == []


def test_build_flow_is_the_four_text_passes_after_the_crawl():
    """The image node is not ported: text-only by decision, so no out_dir and
    no image provider in shared core."""
    from crawl.analyses.product_intent import nodes as n
    node = product_intent.build_flow().start_node
    seen = [type(node).__name__]
    while node.successors:
        node = node.successors["default"]
        seen.append(type(node).__name__)
    assert seen == ["FetchRepo", "PainScene", "VariantSentence",
                    "CompetitivePositioning", "SurprisesAndAbsences"]
    assert not hasattr(n, "IllustratePain")


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        product_intent.run(argparse.Namespace(repo_path=str(f), out=None))


def test_render_markdown_escapes_pipes_and_newlines_in_the_positioning_table_and_headlines():
    """coderay-q2r.55. A pipe or newline in a model-written cell breaks the
    table for every reader; a newline in a headline lets the next line pose as
    a heading of its own."""
    import json, pathlib
    from crawl.analyses.product_intent import render
    shared = json.loads((pathlib.Path(__file__).parent / "fixtures" / "golden" / "product-intent" / "shared.json").read_text())
    shared["positioning"]["dimensions"][0]["name"] = "Speed | Cost"
    comp = shared["positioning"]["competitors"][0]
    comp["name"] = "Acme|Corp"
    comp["cells"][0].update({"verdict": "Weak\nspot", "detail": "a | b"})
    shared["surprises"]["present"][0]["headline"] = "Fast\n# fake"
    shared["surprises"]["absent"][0]["headline"] = "None\nhere"
    md = render.render_markdown("repo", shared)
    table = [l for l in md.splitlines() if l.startswith("|")]
    pipes = [l.count("|") - l.count("\\|") for l in table]
    assert len(set(pipes)) == 1 and pipes[0] >= 3, table
    assert "### Fast # fake" in md and "\n# fake" not in md
    assert "### None here" in md


def test_render_markdown_keeps_quotes_and_list_items_inside_their_blocks():
    """A newline in the pitch, the pain, a sacrifice or a gain would end the
    blockquote or list item and let the rest become top-level markdown."""
    import json, pathlib
    from crawl.analyses.product_intent import render
    shared = json.loads((pathlib.Path(__file__).parent / "fixtures" / "golden" / "product-intent" / "shared.json").read_text())
    shared["variant"] = "Ship faster.\n# fake pitch"
    shared["pain"] = "Signups dropped.\n# fake pain"
    shared["positioning"]["sacrifices"][0] = "Breadth\n# fake sacrifice"
    shared["positioning"]["gains"][0] = "Depth\n# fake gain"
    md = render.render_markdown("repo", shared)
    assert "\n# fake" not in md
    assert "> Ship faster.\n> # fake pitch" in md and "> Signups dropped.\n> # fake pain" in md
    assert "- Breadth # fake sacrifice" in md and "- Depth # fake gain" in md


def test_render_html_keeps_a_headline_inside_its_div(tmp_path):
    """The HTML twin of the markdown headline: a newline in a model-written
    headline must not become a heading element planted inside the card."""
    import json, pathlib
    from crawl.analyses.product_intent import render
    shared = json.loads((pathlib.Path(__file__).parent / "fixtures" / "golden" / "product-intent" / "shared.json").read_text())
    shared["surprises"]["present"][0]["headline"] = "Fast\n# fake"
    html = render.render_html("repo", shared)
    assert "<h1>fake</h1>" not in html and "Fast # fake" in html
