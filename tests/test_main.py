import json
import os
import subprocess
import sys
from importlib.metadata import version

from crack.analyses.tour.render import (
    MERMAID_SCRIPT,
    available_lenses,
    build_mermaid,
    build_related_links,
    default_output_dir,
    dump_run_state,
    estimate_dry_run_cost,
    format_dry_run_summary,
    format_session_summary,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)
from crack.analyses.tour.nodes import slug


def test_version_flag_prints_installed_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"crack {version('crack')}"


def test_default_output_dir_is_keyed_on_lens():
    beginner = default_output_dir("/some/path/myrepo", "beginner-tutorial")
    architecture = default_output_dir("/some/path/myrepo", "architecture-review")
    assert beginner != architecture
    assert "myrepo" in beginner and "beginner-tutorial" in beginner
    assert "myrepo" in architecture and "architecture-review" in architecture


def test_md_to_html_never_emits_raw_script_tag():
    hostile = "```mermaid\nflowchart TD\n  A --></pre><script>alert(1)</script> B\n```"
    html_out = md_to_html(hostile)
    assert "<script" not in html_out


def test_md_to_html_renders_plain_markdown():
    assert "<h1>Title</h1>" in md_to_html("# Title")


def test_md_to_html_rewrites_mermaid_fence_to_pre_class():
    out = md_to_html("```mermaid\nflowchart TD\n  A --> B\n```")
    assert '<pre class="mermaid">' in out
    assert "flowchart TD" in out


def test_mermaid_label_strips_quotes_and_other_breakout_characters():
    assert '"' not in mermaid_label('Weird "Quoted" Name')
    assert mermaid_label("a" * 100) == ("a" * 60)


def test_build_mermaid_handles_quote_in_name():
    abstractions = [{"name": 'Weird "Quoted" Name'}]
    out = build_mermaid(abstractions, [])
    assert 'A0["Weird "Quoted" Name"]' not in out


def test_build_mermaid_renders_extracted_edge_as_solid_arrow():
    abstractions = [{"name": "Foo"}, {"name": "Bar"}]
    relationships = [{"from": "Foo", "to": "Bar", "label": "uses", "source": "EXTRACTED"}]
    out = build_mermaid(abstractions, relationships)
    assert 'A0 -- "uses" --> A1' in out


def test_build_mermaid_renders_inferred_edge_as_dashed_arrow():
    abstractions = [{"name": "Foo"}, {"name": "Bar"}]
    relationships = [{"from": "Foo", "to": "Bar", "label": "guesses", "source": "INFERRED"}]
    out = build_mermaid(abstractions, relationships)
    assert 'A0 -. "guesses" .-> A1' in out


def test_mermaid_script_is_pinned_and_has_integrity():
    assert "mermaid/dist/mermaid.min.js\"" not in MERMAID_SCRIPT  # unpinned "latest"
    assert "@11.17.2/dist/mermaid.min.js" in MERMAID_SCRIPT
    assert 'integrity="sha384-' in MERMAID_SCRIPT


def test_available_lenses_matches_instructions_directory():
    lenses = available_lenses()
    assert lenses == sorted(lenses)
    assert "beginner-tutorial" in lenses
    assert "architecture-review" in lenses
    assert "security-audit" in lenses
    assert "onboarding-guide" in lenses


def _chapters():
    return [
        {"name": "First", "filename": "01_first.md", "content": "# First\n\ncontent"},
        {"name": "Second", "filename": "02_second.md", "content": "# Second\n\n[back](01_first.md)"},
    ]


def test_chapter_link_rewrite_matches_crack_nodes_filename_convention(tmp_path):
    # Regression for coderay-e06: crack.analyses.tour.nodes generates chapter filenames via
    # slug(), and write_chapter_files's link-rewrite regex has to recognize
    # whatever alphabet slug() produces, or generated links silently 404.
    names = ["Getting Started!", "API & Auth", "C++ Bindings"]
    filenames = {n: f"{i+1:02d}_{slug(n)}.md" for i, n in enumerate(names)}
    chapters = [
        {"name": n, "filename": filenames[n], "content": f"# {n}"} for n in names
    ]
    chapters[0]["content"] = f"See [{names[1]}]({filenames[names[1]]}) next."

    write_chapter_files(chapters, "repo", str(tmp_path), [], generated_at="2026-08-31")

    first_html = (tmp_path / chapters[0]["filename"].replace(".md", ".html")).read_text(encoding="utf-8")
    assert f"{filenames[names[1]][:-3]}.html" in first_html
    assert filenames[names[1]] not in first_html  # the .md link got rewritten, not left dangling


def test_write_chapter_files_writes_md_and_html_with_nav_links(tmp_path):
    chapters = _chapters()
    write_chapter_files(chapters, "myrepo", str(tmp_path), [], generated_at="2026-08-31")

    assert (tmp_path / "01_first.md").read_text(encoding="utf-8") == "# First\n\ncontent"
    html_out = (tmp_path / "02_second.html").read_text(encoding="utf-8")
    assert "01_first.html" in html_out  # markdown link rewritten to .html
    assert "&larr;" in html_out  # prev link present for the second chapter
    assert (tmp_path / "01_first.html").exists()


def test_write_chapter_files_adds_related_section_for_outgoing_and_incoming_edges(tmp_path):
    chapters = _chapters()
    relationships = [{"from": "First", "to": "Second", "label": "uses"}]

    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships, generated_at="2026-08-31")

    first_html = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    second_html = (tmp_path / "02_second.html").read_text(encoding="utf-8")

    assert "uses" in first_html
    assert "02_second.html" in first_html  # outgoing edge links to the other chapter

    assert "uses" in second_html
    assert "01_first.html" in second_html  # incoming edge links back


def test_write_chapter_files_escapes_relationship_label_and_names(tmp_path):
    # Regression: relationships come from an LLM call (coderay-o41); this project
    # already shipped a stored-XSS bug once (see CLAUDE.md). Relate validates the
    # fields exist and are strings (tests/test_nodes.py) but not their content.
    chapters = _chapters()
    relationships = [{"from": "First", "to": "Second", "label": '<script>alert(1)</script>'}]

    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships, generated_at="2026-08-31")

    first_html = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in first_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in first_html


def test_build_related_links_caps_label_length():
    filenames = {"First": "01_first.md", "Second": "02_second.md"}
    relationships = [{"from": "First", "to": "Second", "label": "x" * 200}]

    links = build_related_links("First", relationships, filenames)

    assert len(links) == 1
    assert "x" * 200 not in links[0]
    assert "x" * 60 in links[0]


def test_write_chapter_files_skips_relationship_referencing_unknown_abstraction(tmp_path):
    chapters = _chapters()
    relationships = [{"from": "First", "to": "Missing", "label": "uses"}]

    # Should not raise even though "Missing" has no chapter/filename.
    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships, generated_at="2026-08-31")

    first_html = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    assert "Missing" not in first_html


def test_write_index_md_lists_chapters_and_mermaid(tmp_path):
    write_index_md(_chapters(), "myrepo", "beginner-tutorial", "a summary", "flowchart TD", str(tmp_path), generated_at="2026-08-31")
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "# myrepo" in out
    assert "[First](01_first.md)" in out
    assert "flowchart TD" in out


def test_write_index_md_includes_mermaid_legend(tmp_path):
    write_index_md(_chapters(), "myrepo", "beginner-tutorial", "a summary", "flowchart TD", str(tmp_path), generated_at="2026-08-31")
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "dashed arrows are the model's judgment" in out


def test_write_index_html_includes_mermaid_legend(tmp_path):
    write_index_html(
        _chapters(), "myrepo", "beginner-tutorial", "a summary",
        "flowchart TD", ["a.py"], "because", str(tmp_path),
        generated_at="2026-08-31",
    )
    out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "dashed arrows are the model&#x27;s judgment" in out


def test_write_index_html_escapes_summary_and_lists_files(tmp_path):
    write_index_html(
        _chapters(), "myrepo", "beginner-tutorial", "a <script> summary",
        "flowchart TD", ["a.py", "b.py"], "because", str(tmp_path),
        generated_at="2026-08-31",
    )
    out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script> summary" not in out
    assert "&lt;script&gt; summary" in out
    assert "a.py" in out and "b.py" in out


def test_write_index_html_includes_staleness_disclaimer(tmp_path):
    write_index_html(
        _chapters(), "myrepo", "beginner-tutorial", "a summary",
        "flowchart TD", ["a.py"], "because", str(tmp_path),
        generated_at="2026-08-31",
    )
    out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "2026-08-31" in out
    assert "snapshot" in out.lower()


def test_write_index_md_includes_staleness_disclaimer(tmp_path):
    write_index_md(
        _chapters(), "myrepo", "beginner-tutorial", "a summary", "flowchart TD",
        str(tmp_path), generated_at="2026-08-31",
    )
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "2026-08-31" in out
    assert "snapshot" in out.lower()


def test_write_chapter_files_includes_staleness_disclaimer(tmp_path):
    write_chapter_files(_chapters(), "myrepo", str(tmp_path), [], generated_at="2026-08-31")
    out = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    assert "2026-08-31" in out
    assert "snapshot" in out.lower()


def test_write_chapter_files_escapes_staleness_disclaimer(tmp_path):
    write_chapter_files(_chapters(), "myrepo", str(tmp_path), [], generated_at='<script>alert(1)</script>')
    out = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_write_index_html_escapes_staleness_disclaimer(tmp_path):
    write_index_html(
        _chapters(), "myrepo", "beginner-tutorial", "a summary",
        "flowchart TD", ["a.py"], "because", str(tmp_path),
        generated_at='<script>alert(1)</script>',
    )
    out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_dump_run_state_captures_partial_progress(tmp_path):
    shared = {
        "selected_files": ["a.py", "b.py"],
        "abstractions": [{"name": "Foo"}, {"name": "Bar"}],
        "order": ["Foo", "Bar"],
    }
    path = dump_run_state(shared, str(tmp_path))

    state = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert path == str(tmp_path / "run_state.json")
    assert state["selected_files"] == ["a.py", "b.py"]
    assert state["abstractions"] == ["Foo", "Bar"]
    assert state["chapters_completed"] is None


def test_format_session_summary_reports_unknown_cost_for_an_unpriced_model():
    usage = [{
        "provider": "openai", "model": "gpt-6-mystery",
        "input_tokens": 100, "output_tokens": 50,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "duration_s": 1.5, "cached": False,
    }]
    out = format_session_summary(usage, wall_seconds=8.0)
    assert "Session" in out
    assert "Total cost:            unknown" in out
    assert "Total duration (API):  2s" in out
    assert "Total duration (wall): 8s" in out
    assert "Usage:                 100 input, 50 output, 0 cache read, 0 cache write" in out


def test_format_session_summary_sums_cost_across_records_for_a_priced_model():
    usage = [
        {
            "provider": "anthropic", "model": "claude-sonnet-5",
            "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "duration_s": 1.0, "cached": False,
        },
        {
            "provider": "anthropic", "model": "claude-sonnet-5",
            "input_tokens": 0, "output_tokens": 1_000_000,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "duration_s": 2.0, "cached": False,
        },
    ]
    out = format_session_summary(usage, wall_seconds=5.0)
    assert "Total cost:            $12.0000" in out
    assert "Total duration (API):  3s" in out


def test_format_session_summary_handles_empty_usage():
    out = format_session_summary([], wall_seconds=0.4)
    assert "Total cost:            $0.0000" in out
    assert "Usage:                 0 input, 0 output, 0 cache read, 0 cache write" in out


def test_dump_run_state_handles_empty_shared(tmp_path):
    dump_run_state({}, str(tmp_path))
    state = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert state == {
        "selected_files": None,
        "abstractions": None,
        "order": None,
        "relationships": None,
        "chapters_completed": None,
    }


def _make_repo_files(tmp_path, count, size=500):
    for i in range(count):
        (tmp_path / f"file_{i}.py").write_text("x" * size, encoding="utf-8")


def test_estimate_dry_run_cost_returns_a_cost_range_for_a_priced_model(tmp_path):
    _make_repo_files(tmp_path, count=5)

    estimate = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "anthropic", "claude-sonnet-5")

    assert estimate["chapter_guess"] == 8
    assert estimate["estimated_input_tokens"] > 0
    assert estimate["estimated_output_tokens_worst_case"] > 0
    assert estimate["cost_low"] is not None
    assert estimate["cost_high"] is not None
    assert estimate["cost_low"] <= estimate["cost_high"]


def test_estimate_dry_run_cost_is_unpriced_for_an_unknown_model(tmp_path):
    _make_repo_files(tmp_path, count=3)

    estimate = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "openai", "gpt-6-mystery")

    assert estimate["cost_low"] is None
    assert estimate["cost_high"] is None


def test_format_dry_run_summary_shows_the_chapter_assumption_and_cost_range():
    estimate = {
        "provider": "anthropic", "model": "claude-sonnet-5", "chapter_guess": 8,
        "estimated_input_tokens": 1000, "estimated_output_tokens_worst_case": 5000,
        "cost_low": 0.01, "cost_high": 0.05,
    }
    out = format_dry_run_summary(estimate)
    assert "Estimated cost (dry run)" in out
    assert "Assumes ~8 chapters" in out
    assert "$0.0100 - $0.0500" in out
    assert "~1000 input tokens" in out
    assert "~5000 output tokens" in out
    assert "does not account for prompt caching" in out


def test_format_dry_run_summary_shows_unknown_for_an_unpriced_model():
    estimate = {
        "provider": "openai", "model": "gpt-6-mystery", "chapter_guess": 8,
        "estimated_input_tokens": 1000, "estimated_output_tokens_worst_case": 5000,
        "cost_low": None, "cost_high": None,
    }
    out = format_dry_run_summary(estimate)
    assert "unknown" in out


def test_dry_run_flag_estimates_without_creating_the_output_directory(tmp_path, monkeypatch):
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    env = dict(os.environ, ANTHROPIC_API_KEY="test-key", XDG_CONFIG_HOME=str(tmp_path / "config"))
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        env.pop(var, None)

    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "tour", str(repo), "--dry-run", "--out", str(out_dir)],
        capture_output=True, text=True, env=env, check=True,
    )

    assert "Estimated cost (dry run)" in result.stdout
    assert not out_dir.exists()


def test_dry_run_flag_works_with_no_llm_key_configured(tmp_path):
    # The spec requires --dry-run to need no API key at all -- it falls back
    # to the anthropic default when resolve_provider_and_model() can't find one.
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "config"))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        env.pop(var, None)

    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "tour", str(repo), "--dry-run"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0
    assert "Estimated cost (dry run)" in result.stdout
