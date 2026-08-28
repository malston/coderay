"""CLI for Chapter 3's Codebase Knowledge Builder.

Usage:
    python -m workflow.main path/to/repo
    python -m workflow.main path/to/repo --out ../output/vscode-tour
    python -m workflow.main path/to/repo --instructions architecture-review

The --instructions flag swaps the lens (§3.4):
    beginner-tutorial   (default)
    architecture-review
    security-audit
    onboarding-guide
"""
import argparse
import html
import os
import re

from markdown_it import MarkdownIt

from workflow.flow import create_tour_flow
from workflow.nodes import INSTRUCTIONS_DIR, PipelineState

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
        lambda m: f'<pre class="mermaid">{m.group(1)}</pre>',
        rendered,
        flags=re.DOTALL,
    )


def mermaid_label(s):
    """Mermaid labels have no escape syntax; restrict to characters that can't break out."""
    return re.sub(r'[^\w .,:/()\[\]-]', '', s)[:60]


def build_mermaid(abstractions, relationships):
    ids = {a["name"]: f"A{i}" for i, a in enumerate(abstractions)}
    lines = ["flowchart TD"]
    for i, a in enumerate(abstractions):
        lines.append(f'    A{i}["{mermaid_label(a["name"])}"]')
    for r in relationships:
        if r["from"] in ids and r["to"] in ids:
            lines.append(f'    {ids[r["from"]]} -- "{mermaid_label(r["label"][:30])}" --> {ids[r["to"]]}')
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
<script
  src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
  integrity="sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2"
  crossorigin="anonymous"
></script>
<script>mermaid.initialize({ startOnLoad: true, theme: 'neutral', securityLevel: 'strict' });</script>"""


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


def available_lenses():
    return sorted(f[:-3] for f in os.listdir(INSTRUCTIONS_DIR) if f.endswith(".md"))


def write_text(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_chapter_files(chapters, repo_name, out):
    """Write each chapter's .md and .html, with prev/next links between them."""
    for i, ch in enumerate(chapters):
        write_text(os.path.join(out, ch["filename"]), ch["content"])

        prev_link = (
            f'<a href="{chapter_html_name(chapters[i-1]["filename"])}">&larr; {html.escape(chapters[i-1]["name"])}</a>'
            if i > 0 else "&nbsp;"
        )
        next_link = (
            f'<a href="{chapter_html_name(chapters[i+1]["filename"])}">{html.escape(chapters[i+1]["name"])} &rarr;</a>'
            if i < len(chapters) - 1 else "&nbsp;"
        )
        # Rewrite relative chapter links (as generated by workflow.nodes.slug())
        # to point at .html files. Scoped to relative links, not e.g. an external
        # https://example.com/README.md the LLM happened to cite.
        body_md = re.sub(
            r'\]\((?!\w+://)([^)]+)\.md\)',
            lambda m: f']({m.group(1)}.html)',
            ch["content"],
        )
        chapter_html = CHAPTER_HTML_TEMPLATE.format(
            title=f'{html.escape(ch["name"])} — {html.escape(repo_name)}',
            shared_style=SHARED_STYLE,
            mermaid_script=MERMAID_SCRIPT,
            repo_name=html.escape(repo_name),
            body_html=md_to_html(body_md),
            prev_link=prev_link,
            next_link=next_link,
        )
        write_text(os.path.join(out, chapter_html_name(ch["filename"])), chapter_html)


def write_index_md(chapters, repo_name, lens, summary, mermaid, out):
    index_md_parts = [
        f"# {repo_name}\n",
        f"_Lens: {lens}_\n",
        f"{summary}\n",
        "## Architecture\n",
        f"```mermaid\n{mermaid}\n```\n",
        "## Chapters\n",
    ]
    for ch in chapters:
        index_md_parts.append(f"- [{ch['name']}]({ch['filename']})")
    write_text(os.path.join(out, "index.md"), "\n".join(index_md_parts))


def write_index_html(chapters, repo_name, lens, summary, mermaid, selected_files, selection_reasoning, out):
    chapter_list_html = "\n".join(
        f'    <li><a href="{chapter_html_name(ch["filename"])}">{html.escape(ch["name"])}</a></li>'
        for ch in chapters
    )
    files_list_html = "\n".join(
        f'    <li><code>{html.escape(f)}</code></li>' for f in selected_files
    )
    rendered = INDEX_HTML_TEMPLATE.format(
        repo_name=html.escape(repo_name),
        lens=lens,
        n_chapters=len(chapters),
        n_files=len(selected_files),
        summary=html.escape(summary.strip().replace("\n", " ")),
        mermaid=mermaid,
        chapter_list_html=chapter_list_html,
        files_list_html=files_list_html,
        reasoning_html=md_to_html(selection_reasoning),
        shared_style=SHARED_STYLE,
        mermaid_script=MERMAID_SCRIPT,
    )
    write_text(os.path.join(out, "index.html"), rendered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_path")
    ap.add_argument("--out", default=None)
    ap.add_argument("--instructions", default="beginner-tutorial", choices=available_lenses())
    args = ap.parse_args()

    if not os.path.isdir(args.repo_path):
        ap.error(f"{args.repo_path} is not a directory")

    name = os.path.basename(os.path.abspath(args.repo_path))
    out = args.out or os.path.join(os.path.dirname(__file__), "..", "output", f"{name}-tour")
    os.makedirs(out, exist_ok=True)

    shared: PipelineState = {"repo_path": args.repo_path, "instructions": args.instructions}
    create_tour_flow().run(shared)

    chapters = shared["chapters"]
    mermaid = build_mermaid(shared["abstractions"], shared["relationships"])

    write_chapter_files(chapters, name, out)
    write_index_md(chapters, name, args.instructions, shared["summary"], mermaid, out)
    write_index_html(
        chapters, name, args.instructions, shared["summary"], mermaid,
        shared["selected_files"], shared["selection_reasoning"], out,
    )

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")


if __name__ == "__main__":
    main()
