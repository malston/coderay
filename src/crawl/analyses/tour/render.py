"""Rendering, cost estimation, and session-summary formatting for the tour analysis."""
import html
import json
import os
import re
from datetime import date

from markdown_it import MarkdownIt

from crawl.core.render import markdown_parser

from crawl.core import (
    cost_for, fill, list_files, max_output_tokens,
    read_prompt, safe_read,
)
from crawl.analyses.tour.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    SmartCrawl,
    load_instructions,
)

# CommonMark parser. Unlike python-markdown's fenced_code extension, this
# correctly handles fenced code blocks indented inside list items.
_MD = markdown_parser("strikethrough", image=True)


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


MERMAID_LEGEND = (
    "Solid arrows are backed by a real import between the files each abstraction claims; "
    "dashed arrows are the model's judgment."
)


def build_mermaid(abstractions, relationships):
    ids = {a["name"]: f"A{i}" for i, a in enumerate(abstractions)}
    lines = ["flowchart TD"]
    for i, a in enumerate(abstractions):
        lines.append(f'    A{i}["{mermaid_label(a["name"])}"]')
    for r in relationships:
        if r["from"] in ids and r["to"] in ids:
            label = mermaid_label(r["label"][:30])
            arrow = "--" if r.get("source") == "EXTRACTED" else "-."
            head = "-->" if r.get("source") == "EXTRACTED" else ".->"
            lines.append(f'    {ids[r["from"]]} {arrow} "{label}" {head} {ids[r["to"]]}')
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
  nav.chapter-nav { margin: 2em 0 0; padding: 1em 0; border-top: 1px solid var(--rule); display: flex; justify-content: space-between; font-size: .95em; }
  .staleness { font-size: .85em; }"""

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
  <p class="muted staleness">{staleness}</p>
  <p>{summary}</p>

  <h2>Architecture map</h2>
  <pre class="mermaid">
{mermaid}
  </pre>
  <p class="muted">{mermaid_legend}</p>

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
  <p class="muted staleness">{staleness}</p>
{body_html}
  <nav class="chapter-nav">
    <span>{prev_link}</span>
    <span>{next_link}</span>
  </nav>
</body>
</html>
"""


def staleness_disclaimer(generated_at):
    return (
        f"Generated {generated_at} from a snapshot of the code. "
        "May not reflect later changes."
    )


def chapter_html_name(md_name):
    return md_name[:-3] + ".html" if md_name.endswith(".md") else md_name + ".html"


def available_lenses():
    return sorted(p.name[:-3] for p in INSTRUCTIONS_DIR.iterdir() if p.name.endswith(".md"))


def write_text(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def build_related_links(chapter_name, relationships, filenames):
    """Related-chapter links for one chapter, both directions of the Relationship graph.

    Relate validates every edge has a from/to/label string before it reaches shared
    state (crawl/analyses/tour/nodes.py), but an edge naming an abstraction dropped from
    `filenames` by a codebase-budget cut is still possible, so that case is skipped
    rather than raised.
    """
    links = []
    for r in relationships:
        from_name, to_name, label = r["from"], r["to"], html.escape(r["label"][:60])
        if from_name == chapter_name and to_name in filenames:
            href = chapter_html_name(filenames[to_name])
            links.append(f'<li>&rarr; {label} &rarr; <a href="{href}">{html.escape(to_name)}</a></li>')
        elif to_name == chapter_name and from_name in filenames:
            href = chapter_html_name(filenames[from_name])
            links.append(f'<li>&larr; {label} &larr; <a href="{href}">{html.escape(from_name)}</a></li>')
    return links


def write_chapter_files(chapters, repo_name, out, relationships, generated_at):
    """Write each chapter's .md and .html, with prev/next links and a Related section."""
    filenames = {ch["name"]: ch["filename"] for ch in chapters}
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
        # Rewrite relative chapter links (as generated by crawl.analyses.tour.nodes.slug())
        # to point at .html files. Scoped to relative links, not e.g. an external
        # https://example.com/README.md the LLM happened to cite.
        body_md = re.sub(
            r'\]\((?!\w+://)([^)]+)\.md\)',
            lambda m: f']({m.group(1)}.html)',
            ch["content"],
        )
        related_links = build_related_links(ch["name"], relationships, filenames)
        related_html = (
            f'<h2>Related</h2>\n<ul>\n{"".join(related_links)}\n</ul>\n' if related_links else ""
        )
        chapter_html = CHAPTER_HTML_TEMPLATE.format(
            title=f'{html.escape(ch["name"])} — {html.escape(repo_name)}',
            shared_style=SHARED_STYLE,
            mermaid_script=MERMAID_SCRIPT,
            repo_name=html.escape(repo_name),
            body_html=md_to_html(body_md) + related_html,
            prev_link=prev_link,
            next_link=next_link,
            staleness=html.escape(staleness_disclaimer(generated_at)),
        )
        write_text(os.path.join(out, chapter_html_name(ch["filename"])), chapter_html)


def write_index_md(chapters, repo_name, lens, summary, mermaid, out, generated_at):
    index_md_parts = [
        f"# {repo_name}\n",
        f"_Lens: {lens}_\n",
        f"_{staleness_disclaimer(generated_at)}_\n",
        f"{summary}\n",
        "## Architecture\n",
        f"```mermaid\n{mermaid}\n```\n",
        f"_{MERMAID_LEGEND}_\n",
        "## Chapters\n",
    ]
    for ch in chapters:
        index_md_parts.append(f"- [{ch['name']}]({ch['filename']})")
    write_text(os.path.join(out, "index.md"), "\n".join(index_md_parts))


def write_index_html(chapters, repo_name, lens, summary, mermaid, selected_files, selection_reasoning, out, generated_at):
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
        mermaid_legend=html.escape(MERMAID_LEGEND),
        chapter_list_html=chapter_list_html,
        files_list_html=files_list_html,
        reasoning_html=md_to_html(selection_reasoning),
        shared_style=SHARED_STYLE,
        mermaid_script=MERMAID_SCRIPT,
        staleness=html.escape(staleness_disclaimer(generated_at)),
    )
    write_text(os.path.join(out, "index.html"), rendered)


def format_session_summary(usage_records, wall_seconds):
    """Render the actual-run Session summary from call_llm.get_usage() records
    and total wall-clock seconds. Cost prints as 'unknown' if any record's
    (provider, model) has no pricing entry."""
    total_input = sum(r["input_tokens"] for r in usage_records)
    total_output = sum(r["output_tokens"] for r in usage_records)
    total_cache_read = sum(r["cache_read_tokens"] for r in usage_records)
    total_cache_write = sum(r["cache_write_tokens"] for r in usage_records)
    total_api_duration = sum(r["duration_s"] for r in usage_records)

    costs = [cost_for(r["provider"], r["model"], r) for r in usage_records]
    cost_line = "unknown" if any(c is None for c in costs) else f"${sum(costs):.4f}"

    return (
        "Session\n"
        f"Total cost:            {cost_line}\n"
        f"Total duration (API):  {total_api_duration:.0f}s\n"
        f"Total duration (wall): {wall_seconds:.0f}s\n"
        f"Usage:                 {total_input} input, {total_output} output, "
        f"{total_cache_read} cache read, {total_cache_write} cache write"
    )


# Midpoint of the 5-10 abstractions identify-abstractions.md asks the LLM to find.
DRY_RUN_CHAPTER_GUESS = 8


def _codebase_preview_text(repo_path, budget):
    """Best-guess codebase text for dry-run sizing: the first files
    list_files() returns, up to budget chars. Not the same files the real
    SmartCrawl LLM call would pick, but close enough in total size to
    estimate prompt length."""
    parts = []
    total = 0
    for p in list_files(repo_path):
        if total >= budget:
            break
        text = safe_read(p)
        if text is None:
            continue
        parts.append(text)
        total += len(text)
    return "\n\n".join(parts)


def estimate_dry_run_cost(repo_path, instructions, provider, model, chapter_guess=DRY_RUN_CHAPTER_GUESS):
    """Estimate the cost of a real run without calling any LLM. Input tokens
    use a chars/4 heuristic; output tokens assume every call hits the
    configured max-output cap (a worst-case upper bound, not a typical case)."""
    max_out = max_output_tokens()

    # Reuses SmartCrawl's own prep() for the file-selection prompt instead of
    # rebuilding its preview-manifest logic here -- one source of truth for
    # what that prompt looks like.
    select_prompt, _files, _root = SmartCrawl().prep({"repo_path": repo_path})

    codebase = _codebase_preview_text(repo_path, CODEBASE_BUDGET)
    analyze_prompt = fill(
        read_prompt(PROMPTS_DIR, "identify-abstractions.md"),
        codebase=codebase, selected_files="(estimated -- not yet known)",
    )
    relate_prompt = fill(
        read_prompt(PROMPTS_DIR, "analyze-relationships.md"),
        abstractions="(estimated -- not yet known)", codebase=codebase,
    )
    chapter_prompt = fill(
        read_prompt(PROMPTS_DIR, "write-chapter.md"),
        name="(estimated)", description="(estimated)", chapter_num=1, total=chapter_guess,
        prev_chapters="(estimated)", chapter_list="(estimated)", codebase=codebase,
        instructions=load_instructions(instructions),
    )

    prompts = [select_prompt, analyze_prompt, relate_prompt] + [chapter_prompt] * chapter_guess
    estimated_input_tokens = sum(len(p) // 4 for p in prompts)
    estimated_output_tokens_worst_case = max_out * len(prompts)

    low_usage = {"input_tokens": estimated_input_tokens, "output_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_tokens": 0}
    high_usage = {"input_tokens": estimated_input_tokens, "output_tokens": estimated_output_tokens_worst_case,
                  "cache_read_tokens": 0, "cache_write_tokens": 0}

    return {
        "provider": provider, "model": model, "chapter_guess": chapter_guess,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens_worst_case": estimated_output_tokens_worst_case,
        "cost_low": cost_for(provider, model, low_usage),
        "cost_high": cost_for(provider, model, high_usage),
    }


def format_dry_run_summary(estimate):
    if estimate["cost_low"] is None or estimate["cost_high"] is None:
        cost_line = "unknown (no pricing for this model)"
    else:
        cost_line = f"${estimate['cost_low']:.4f} - ${estimate['cost_high']:.4f}"
    return (
        "Estimated cost (dry run)\n"
        f"Assumes ~{estimate['chapter_guess']} chapters (actual count depends on the repo)\n"
        f"Estimated cost:  {cost_line}\n"
        f"Estimated usage: ~{estimate['estimated_input_tokens']} input tokens, "
        f"up to ~{estimate['estimated_output_tokens_worst_case']} output tokens\n"
        "Note: this estimate does not account for prompt caching -- a real run "
        "reuses the same codebase block across calls, so actual cost is often "
        "lower than the low end shown here."
    )


def dump_run_state(shared: PipelineState, out):
    """Write a summary of the pipeline's progress (selected files, abstraction
    and chapter names, order, relationships) to run_state.json, for post-mortem
    on an unhandled failure deep into a run (e.g. the 3rd LLM retry still failing
    on chapter 7 of 10)."""
    state = {
        "selected_files": shared.get("selected_files"),
        "abstractions": [a["name"] for a in shared["abstractions"]] if shared.get("abstractions") else None,
        "order": shared.get("order"),
        "relationships": shared.get("relationships"),
        "chapters_completed": [c["name"] for c in shared["chapters"]] if shared.get("chapters") else None,
    }
    path = os.path.join(out, "run_state.json")
    write_text(path, json.dumps(state, indent=2))
    return path


def default_output_dir(repo_path, instructions):
    """Keyed on both repo name and lens, so re-running with a different
    --instructions writes to a separate directory instead of colliding with
    (and leaving orphaned chapter files from) a prior run's output. Anchored
    on the current working directory, not this file's location, so it lands
    in the same place whether crawl is run from an editable checkout or
    installed as a tool."""
    name = os.path.basename(os.path.abspath(repo_path))
    return os.path.join(os.getcwd(), "output", f"{name}-{instructions}-tour")
