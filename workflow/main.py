"""CLI for Chapter 3's Codebase Knowledge Builder.

Usage:
    python main.py path/to/repo
    python main.py path/to/repo --out ../output/vscode-tour
    python main.py path/to/repo --instructions architecture-review

The --instructions flag swaps the lens (§3.4):
    beginner-tutorial   (default)
    architecture-review
    security-audit
    onboarding-guide
"""
import argparse, html, os, re
from markdown_it import MarkdownIt
from flow import create_tour_flow

# CommonMark parser. Unlike python-markdown's fenced_code extension, this
# correctly handles fenced code blocks indented inside list items.
_MD = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False}).enable(["table", "strikethrough"])


def md_to_html(md_text):
    """Markdown to HTML, plus rewire ```mermaid blocks so the mermaid JS finds them."""
    rendered = _MD.render(md_text)
    # markdown-it produces <pre><code class="language-mermaid">...</code></pre>.
    # mermaid.js looks for <pre class="mermaid">...</pre>. Rewrite.
    return re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<pre class="mermaid">{html.unescape(m.group(1))}</pre>',
        rendered,
        flags=re.DOTALL,
    )


def build_mermaid(abstractions, relationships):
    ids = {a["name"]: f"A{i}" for i, a in enumerate(abstractions)}
    lines = ["flowchart TD"]
    for i, a in enumerate(abstractions):
        lines.append(f'    A{i}["{a["name"]}"]')
    for r in relationships:
        if r["from"] in ids and r["to"] in ids:
            lines.append(f'    {ids[r["from"]]} -- "{r["label"][:30]}" --> {ids[r["to"]]}')
    return "\n".join(lines)


SHARED_STYLE = """\
  :root { --fg: #0d1117; --muted: #57606a; --bg: #fff; --soft: #f6f8fa; --accent: #0969da; --rule: #d0d7de; }
  body { font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         color: var(--fg); background: var(--bg); margin: 0 auto; max-width: 880px; padding: 32px 24px; }
  h1 { font-size: 1.9em; margin: 0 0 .2em; }
  h2 { font-size: 1.35em; margin: 1.8em 0 .4em; padding-bottom: .2em; border-bottom: 1px solid var(--rule); }
  h3 { font-size: 1.1em; margin: 1.4em 0 .3em; }
  p, li, td, th { color: var(--fg); }
  p { margin: .8em 0; }
  .muted { color: var(--muted); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  ul, ol { padding-left: 1.4em; }
  li { margin: .35em 0; }
  code { font: .9em/1.4 ui-monospace, "SF Mono", Consolas, monospace; background: var(--soft); padding: 1px 5px; border-radius: 3px; }
  pre { background: var(--soft); padding: 14px 16px; border-radius: 6px; overflow-x: auto; }
  pre code { background: none; padding: 0; font-size: .88em; }
  pre.mermaid { background: var(--soft); padding: 16px; text-align: center; }
  blockquote { border-left: 3px solid var(--rule); margin: 1em 0; padding: .2em 1em; color: var(--muted); }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid var(--rule); padding: 8px 10px; text-align: left; font-size: .92em; }
  th { background: var(--soft); }
  .lens { display: inline-block; padding: 2px 8px; background: var(--soft); border-radius: 4px; font-size: .85em; }
  nav.chapter-nav { margin: 2em 0 0; padding: 1em 0; border-top: 1px solid var(--rule); display: flex; justify-content: space-between; font-size: .95em; }"""

MERMAID_SCRIPT = """\
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script>mermaid.initialize({ startOnLoad: true, theme: 'neutral' });</script>"""


INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{repo_name} tour</title>
<style>
{shared_style}
</style>
{mermaid_script}
</head>
<body>
  <h1>{repo_name}</h1>
  <p class="muted">Lens: <span class="lens">{lens}</span> &middot; {n_chapters} chapters &middot; {n_files} files analyzed</p>
  <p>{summary}</p>

  <h2>Architecture map</h2>
  <pre class="mermaid">
{mermaid}
  </pre>

  <h2>Read in order</h2>
  <ol>
{chapter_list_html}
  </ol>

  <h2>Files the LLM picked</h2>
{reasoning_html}
  <ul class="files">
{files_list_html}
  </ul>
</body>
</html>
"""


CHAPTER_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{shared_style}
</style>
{mermaid_script}
</head>
<body>
  <p class="muted"><a href="index.html">&larr; {repo_name} tour</a></p>
{body_html}
  <nav class="chapter-nav">
    <span>{prev_link}</span>
    <span>{next_link}</span>
  </nav>
</body>
</html>
"""


def chapter_html_name(md_name):
    return md_name[:-3] + ".html" if md_name.endswith(".md") else md_name + ".html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_path")
    ap.add_argument("--out", default=None)
    ap.add_argument("--instructions", default="beginner-tutorial",
                    choices=["beginner-tutorial", "architecture-review",
                             "security-audit", "onboarding-guide"])
    args = ap.parse_args()

    assert os.path.isdir(args.repo_path), f"{args.repo_path} is not a directory"

    name = os.path.basename(os.path.abspath(args.repo_path).rstrip('/'))
    out = args.out or os.path.join(os.path.dirname(__file__), "..", "output", f"{name}-tour")
    os.makedirs(out, exist_ok=True)

    shared = {"repo_path": args.repo_path, "instructions": args.instructions}
    create_tour_flow().run(shared)

    # Per chapter markdown + HTML
    chapters = shared["chapters"]
    for i, ch in enumerate(chapters):
        md_path = os.path.join(out, ch["filename"])
        open(md_path, "w").write(ch["content"])

        prev_link = (
            f'<a href="{chapter_html_name(chapters[i-1]["filename"])}">&larr; {chapters[i-1]["name"]}</a>'
            if i > 0 else "&nbsp;"
        )
        next_link = (
            f'<a href="{chapter_html_name(chapters[i+1]["filename"])}">{chapters[i+1]["name"]} &rarr;</a>'
            if i < len(chapters) - 1 else "&nbsp;"
        )
        # Rewrite markdown chapter links to point at .html files.
        body_md = re.sub(
            r'\]\((\d+_[a-z0-9_]+)\.md\)',
            lambda m: f']({m.group(1)}.html)',
            ch["content"],
        )
        chapter_html = CHAPTER_HTML_TEMPLATE.format(
            title=f'{ch["name"]} — {name}',
            shared_style=SHARED_STYLE,
            mermaid_script=MERMAID_SCRIPT,
            repo_name=name,
            body_html=md_to_html(body_md),
            prev_link=prev_link,
            next_link=next_link,
        )
        open(os.path.join(out, chapter_html_name(ch["filename"])), "w").write(chapter_html)

    # Index markdown
    mermaid = build_mermaid(shared["abstractions"], shared["relationships"])
    index_md_parts = [
        f"# {name}\n",
        f"_Lens: {args.instructions}_\n",
        f"{shared['summary']}\n",
        "## Architecture\n",
        f"```mermaid\n{mermaid}\n```\n",
        "## Chapters\n",
    ]
    for ch in chapters:
        index_md_parts.append(f"- [{ch['name']}]({ch['filename']})")
    open(os.path.join(out, "index.md"), "w").write("\n".join(index_md_parts))

    # Index HTML
    chapter_list_html = "\n".join(
        f'    <li><a href="{chapter_html_name(ch["filename"])}">{ch["name"]}</a></li>'
        for ch in chapters
    )
    files_list_html = "\n".join(
        f'    <li><code>{f}</code></li>' for f in shared["selected_files"]
    )
    reasoning_html = md_to_html(shared["selection_reasoning"])
    rendered = INDEX_HTML_TEMPLATE.format(
        repo_name=name,
        lens=args.instructions,
        n_chapters=len(chapters),
        n_files=len(shared["selected_files"]),
        summary=html.escape(shared["summary"].strip().replace("\n", " ")),
        mermaid=mermaid,
        chapter_list_html=chapter_list_html,
        files_list_html=files_list_html,
        reasoning_html=reasoning_html,
        shared_style=SHARED_STYLE,
        mermaid_script=MERMAID_SCRIPT,
    )
    open(os.path.join(out, "index.html"), "w").write(rendered)

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")


if __name__ == "__main__":
    main()
