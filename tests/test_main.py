from main import (
    MERMAID_SCRIPT,
    available_lenses,
    build_mermaid,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)


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


def test_write_chapter_files_writes_md_and_html_with_nav_links(tmp_path):
    write_chapter_files(_chapters(), "myrepo", str(tmp_path))

    assert (tmp_path / "01_first.md").read_text(encoding="utf-8") == "# First\n\ncontent"
    html_out = (tmp_path / "02_second.html").read_text(encoding="utf-8")
    assert "01_first.html" in html_out  # markdown link rewritten to .html
    assert "&larr;" in html_out  # prev link present for the second chapter
    assert (tmp_path / "01_first.html").exists()


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
