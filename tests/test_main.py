from main import md_to_html


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
