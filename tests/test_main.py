from main import build_mermaid, md_to_html, mermaid_label


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
