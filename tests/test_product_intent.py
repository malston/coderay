import argparse
import os

import pytest

from crack.analyses import ANALYSES, product_intent


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
    from crack.analyses.product_intent import nodes as n
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
