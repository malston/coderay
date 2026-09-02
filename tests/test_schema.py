import argparse

import pytest

from crack.analyses import ANALYSES, schema


def test_schema_is_registered():
    assert ANALYSES["schema"] is schema
    assert schema.NAME == "schema"


def test_schema_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(schema, attr), attr


def test_schema_declares_the_card_family_contract():
    assert len(schema.SECTIONS) == 4
    assert [s.key for s in schema.SECTIONS] == [
        "tour_md", "flows_md", "deepdive_md", "migration_md"]
    assert [s.width for s in schema.SECTIONS] == [400, 400, 480, 420]
    assert schema.THEME.title_suffix == "schema"


def test_schema_does_not_raise_the_output_token_ceiling():
    """The deep dive batches four tables per call instead, so the default cap
    is enough. The other card analyses raise it; this one must not, or the
    batching is paying for nothing."""
    assert schema.ENV_DEFAULTS == {}


def test_the_migration_section_renders_a_note_rather_than_vanishing():
    """A missing history is a finding about the repo, so unlike the interfaces
    tour it stays on the page and explains itself."""
    migration = next(s for s in schema.SECTIONS if s.key == "migration_md")
    assert migration.when_empty == "skip-note"
    assert "only 2 migrations found" in migration.skip_note({"migration_names": ["a", "b"]})
    assert "only 2 migrations found" in migration.md_skip_note({"migration_names": ["a", "b"]})


def test_add_arguments_adds_the_schema_override_flag():
    """The only analysis with a flag of its own."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    schema.add_arguments(parser)
    args = parser.parse_args(["/tmp/repo", "--schema", "db/schema.rb"])
    assert args.schema == "db/schema.rb"


def test_init_shared_carries_the_repo_path_and_the_override():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None, schema="db/schema.rb")
    assert schema.init_shared(args) == {"repo_path": "/tmp/toy_repo",
                                        "schema_override": "db/schema.rb"}


def test_init_shared_tolerates_an_args_without_the_flag():
    """run_analysis is shared, and other callers build args without --schema."""
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    assert schema.init_shared(args)["schema_override"] is None


def test_build_flow_starts_at_find_schema():
    from crack.analyses.schema.nodes import FindSchema
    assert isinstance(schema.build_flow().start_node, FindSchema)


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not a directory"):
        schema.run(argparse.Namespace(repo_path=str(f), out=None, schema=None))


def test_the_page_is_named_after_the_product_when_the_model_found_one():
    """The only analysis that retitles the page from LLM output."""
    assert schema._page_name({"product_name": "Acme Booking"}, "toy_repo") == "Acme Booking"
    assert schema._page_name({}, "toy_repo") == "toy_repo"
    assert schema._page_name({"product_name": ""}, "toy_repo") == "toy_repo"


def test_overview_spec_names_the_four_sections():
    spec = schema.overview_spec({
        "repo_path": "/tmp/toy_repo", "product_name": "Acme Booking",
        "one_liner": "Bookings against rooms.",
        "table_list": ["users", "orders"], "migration_names": ["a", "b", "c"]})
    assert spec["name"] == "Acme Booking"
    assert [t for t, _ in spec["sections"]] == [
        "The tour", "The flows", "Table deep dive", "Migration history"]
    assert "2 core tables" in spec["facts"]
    assert "3 migrations" in spec["facts"]


def test_the_hero_diagram_escapes_the_erd_it_is_handed():
    html = schema._hero_prefix({"erd": "erDiagram\n</pre><script>alert(1)</script>",
                                "table_list": ["users"]})
    assert "</pre><script>" not in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


def test_the_hero_diagram_is_omitted_when_no_erd_parsed():
    assert schema._hero_prefix({"erd": "", "table_list": ["users"]}) == ""


def test_the_footer_escapes_the_schema_path():
    """schema_path comes off the filesystem, and a repo names its own files."""
    footer = schema._footer({"schema_path": "db/<script>alert(1)</script>.rb",
                             "table_list": [], "migration_names": []})
    assert "<script>" not in footer
    assert "&lt;script&gt;" in footer
