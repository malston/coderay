import json
import subprocess
import sys
from importlib.metadata import version

from workflow.__main__ import (
    MERMAID_SCRIPT,
    available_lenses,
    build_mermaid,
    build_related_links,
    default_output_dir,
    dump_run_state,
    format_session_summary,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)
from workflow.nodes import slug


def test_version_flag_prints_installed_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "workflow", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"coderay {version('coderay')}"


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


def test_chapter_link_rewrite_matches_workflow_nodes_filename_convention(tmp_path):
    # Regression for coderay-e06: workflow.nodes generates chapter filenames via
    # slug(), and write_chapter_files's link-rewrite regex has to recognize
    # whatever alphabet slug() produces, or generated links silently 404.
    names = ["Getting Started!", "API & Auth", "C++ Bindings"]
    filenames = {n: f"{i+1:02d}_{slug(n)}.md" for i, n in enumerate(names)}
    chapters = [
        {"name": n, "filename": filenames[n], "content": f"# {n}"} for n in names
    ]
    chapters[0]["content"] = f"See [{names[1]}]({filenames[names[1]]}) next."

    write_chapter_files(chapters, "repo", str(tmp_path), [])

    first_html = (tmp_path / chapters[0]["filename"].replace(".md", ".html")).read_text(encoding="utf-8")
    assert f"{filenames[names[1]][:-3]}.html" in first_html
    assert filenames[names[1]] not in first_html  # the .md link got rewritten, not left dangling


def test_write_chapter_files_writes_md_and_html_with_nav_links(tmp_path):
    chapters = _chapters()
    write_chapter_files(chapters, "myrepo", str(tmp_path), [])

    assert (tmp_path / "01_first.md").read_text(encoding="utf-8") == "# First\n\ncontent"
    html_out = (tmp_path / "02_second.html").read_text(encoding="utf-8")
    assert "01_first.html" in html_out  # markdown link rewritten to .html
    assert "&larr;" in html_out  # prev link present for the second chapter
    assert (tmp_path / "01_first.html").exists()


def test_write_chapter_files_adds_related_section_for_outgoing_and_incoming_edges(tmp_path):
    chapters = _chapters()
    relationships = [{"from": "First", "to": "Second", "label": "uses"}]

    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships)

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

    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships)

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
    write_chapter_files(chapters, "myrepo", str(tmp_path), relationships)

    first_html = (tmp_path / "01_first.html").read_text(encoding="utf-8")
    assert "Missing" not in first_html


def test_write_index_md_lists_chapters_and_mermaid(tmp_path):
    write_index_md(_chapters(), "myrepo", "beginner-tutorial", "a summary", "flowchart TD", str(tmp_path))
    out = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "# myrepo" in out
    assert "[First](01_first.md)" in out
    assert "flowchart TD" in out


def test_write_index_html_escapes_summary_and_lists_files(tmp_path):
    write_index_html(
        _chapters(), "myrepo", "beginner-tutorial", "a <script> summary",
        "flowchart TD", ["a.py", "b.py"], "because", str(tmp_path),
    )
    out = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script> summary" not in out
    assert "&lt;script&gt; summary" in out
    assert "a.py" in out and "b.py" in out


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
