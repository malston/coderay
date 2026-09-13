"""Rendering, cost estimation, and session-summary formatting for the tour analysis."""
import html
import os
import re
from datetime import date
from typing import NamedTuple

from markdown_it import MarkdownIt

from crawl.core.call_llm import CHARS_PER_TOKEN
from crawl.core.files import write_text_atomic
from crawl.core.pricing import input_ceiling
from crawl.core.render import markdown_parser
from crawl.core.theme import DARK_TOKENS, HEAD_ASSETS, TOKENS

from crawl.core import (
    cost_for, fill, list_files, max_output_tokens,
    read_prompt, safe_read,
)
from crawl.analyses.tour.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    BLOCK_JOIN,
    SmartCrawl,
    block_for,
    load_instructions,
    target_count,
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
  :root { --accent: #0d9488; --accent-soft: #ccfbf1; --accent-ink: #0e6262; }
  body { font-family: var(--font); font-size: 16px; line-height: 1.65;
    color: var(--text); background: var(--bg); margin: 0; -webkit-font-smoothing: antialiased; }
  main { max-width: 820px; margin: 0 auto; padding: 0 24px 64px; }
  h1 { font-size: 1.9rem; font-weight: 800; letter-spacing: -.025em; margin: 1.1em 0 .2em; }
  h2 { font-size: 1.25rem; font-weight: 700; letter-spacing: -.015em; margin: 2em 0 .5em;
    padding-bottom: .3em; border-bottom: 1px solid var(--rule); }
  h3 { font-size: 1.02rem; font-weight: 700; margin: 1.6em 0 .35em; }
  p { margin: .85em 0; color: var(--body-text); }
  ul, ol { padding-left: 1.4em; }
  li { margin: .35em 0; color: var(--body-text); }
  strong { color: var(--text); }
  em { color: var(--body-soft); }
  .muted { color: var(--muted); }
  a { color: var(--accent-ink); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .hero { background: radial-gradient(120% 140% at 50% 0%, #0f766e 0%, #042f2e 70%);
    color: #fff; padding: 46px 20px 42px; text-align: center; }
  .hero-inner { max-width: 1120px; margin: 0 auto; }
  .hero h1 { margin: 12px 0 10px; color: #fff; }
  .hero .sub { font-size: .94rem; color: #99f6e4; margin: 0; line-height: 1.6; }
  .eyebrow { display: inline-flex; align-items: center; gap: 7px; color: #5eead4;
    font-size: .68rem; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
  .eyebrow::before { content: ''; width: 16px; height: 2px; background: #2dd4bf; border-radius: 2px; }
  .hero .lens { background: rgba(255,255,255,.16); color: #ccfbf1; }

  pre { padding: 14px 16px; margin: 1.1em 0; }
  pre code { padding: 0; font-size: .84rem; line-height: 1.55; }
  code { font-size: .88em; padding: 1px 5px; }
  pre.mermaid { background: var(--surface); color: var(--text); border: 1px solid var(--rule);
    border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px; text-align: center; }
  pre.mermaid svg { max-width: 100%; height: auto; }
  blockquote { border-left: 3px solid var(--accent); margin: 1.2em 0; padding: .2em 1.1em; color: var(--body-soft); }
  table { margin: 1.2em 0; font-size: .9rem; }
  th, td { padding: 8px 10px; }
  th { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; }
  .lens { display: inline-block; padding: 2px 9px; background: var(--accent-soft); color: var(--accent-ink);
    border-radius: 999px; font-size: .78rem; font-weight: 600; }
  nav.chapter-nav { margin: 3em 0 0; padding: 1.2em 0 0; border-top: 1px solid var(--rule);
    display: flex; justify-content: space-between; font-size: .92rem; }
  .staleness { font-size: .82rem; }"""


INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{repo_name} tour</title>
{head_assets}
<style>
{tokens}
{shared_style}
{dark_tokens}
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <span class="eyebrow">Guided tour</span>
      <h1>{repo_name}</h1>
      <p class="sub">Lens: <span class="lens">{lens}</span> &middot; {n_chapters} chapters &middot; {n_files} files analyzed</p>
    </div>
  </header>
  <main>
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
  </main>
</body>
</html>
"""


CHAPTER_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
{head_assets}
<style>
{tokens}
{shared_style}
{dark_tokens}
</style>
</head>
<body>
  <main>
  <p class="muted"><a href="index.html">&larr; {repo_name} tour</a></p>
  <p class="muted staleness">{staleness}</p>
{body_html}
  <nav class="chapter-nav">
    <span>{prev_link}</span>
    <span>{next_link}</span>
  </nav>
  </main>
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
    write_text_atomic(path, content)


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
            head_assets=HEAD_ASSETS, tokens=TOKENS, dark_tokens=DARK_TOKENS,
            shared_style=SHARED_STYLE,
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
        head_assets=HEAD_ASSETS, tokens=TOKENS, dark_tokens=DARK_TOKENS,
        shared_style=SHARED_STYLE,
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


#: What SmartCrawl.post adds around a file, measured rather than restated,
#: plus the separator the bundle puts between two of them. Charged to every
#: block rather than to each gap, so the figure rounds up rather than down.
_BLOCK_CHROME = len(block_for("", "")) + len(BLOCK_JOIN)

#: How much heavier the model's pick is than a size-blind one of the same
#: count. Measured on the four recorded runs whose bundle fit under the
#: budget: 0.8x, 1.8x, 2.1x and 2.4x. Those four rounded up, so it is a
#: central correction and not a bound: one of them runs below 1.0, and the
#: estimate reads low on the largest repository measured. Nothing that has to
#: be safe rests on it -- the refusal prediction takes the ceiling instead.
#: Re-measure the band quoted in format_dry_run_summary if this moves.
SELECTION_SKEW = 2.0


class CodebaseEstimate(NamedTuple):
    """What a run would send, and what the figure rests on.

    likely and most differ because two callers want different things: a
    cost figure should be the expectation, and the refusal prediction has
    to be the ceiling. readable and previewed travel with them because a
    number drawn from two files out of two hundred reads exactly as
    confident as one drawn from all of them.
    """
    likely: int
    most: int
    readable: int
    previewed: int


def estimated_codebase_chars(previewed, root, budget, target=None):
    """How many characters of codebase a real run would send.

    A run does not send the repository. SmartCrawl asks the model for
    target_files of them, and SmartCrawl.post bundles those whole, each inside
    a header block, until the budget is spent. Sizing every readable file
    instead put the figure at 1.2x to 5.8x the real bundle across five
    recorded runs, worst on the mid-size ones and closest on a repository big
    enough that both figures were clamped at the budget (coderay-3le).

    Returns what a run is likely to send, and the most it could. Two numbers
    because two callers want different things: a cost figure should be the
    likely one, and the refusal prediction has to be the ceiling. An average
    sits under the real bundle whenever the model picks heavier-than-mean
    files, and a guard whose whole job is to speak before a run is refused
    must not be the thing that stays quiet (coderay-8vk).

    The ceiling is exact: SmartCrawl.exec only accepts indices into the
    files previewed here, so no run can send more than all of them. The
    likely figure is modelled, because which of them the model picks is not
    knowable without asking it.
    """
    sizes = [(len(text), len(os.path.relpath(p, root)))
             for p, text in ((p, safe_read(p)) for p in previewed) if text is not None]
    if not sizes:
        return CodebaseEstimate(0, 0, 0, len(previewed))

    # target_count has a floor of 20, which on a small repository asks for
    # more files than exist. post skips a file it cannot read, so what reads
    # successfully is the ceiling on how many blocks a bundle can hold.
    target = min(target if target is not None else target_count(len(previewed)),
                 len(sizes))
    mean_block = sum(n + path for n, path in sizes) / len(sizes) + _BLOCK_CHROME
    # Skew is what a selection costs. Where the target covers every file there
    # is no selection to be made, so applying it would inflate the one case
    # the estimate can otherwise get exactly right.
    skew = SELECTION_SKEW if target < len(sizes) else 1.0
    whole = sum(n + path for n, path in sizes) + len(sizes) * _BLOCK_CHROME
    # post() tests the budget before appending, so the last block can carry
    # the total past it. The ceiling has to allow for that or it is not one.
    most = min(whole, budget + max(n + path for n, path in sizes) + _BLOCK_CHROME)
    likely = min(budget, whole, target * mean_block * skew)
    return CodebaseEstimate(max(0, int(likely)), max(0, int(most)),
                            len(sizes), len(previewed))


def _codebase_preview_text(chars):
    """Filler standing in for the codebase inside a prompt being sized.

    Only the length of this reaches anything: estimate_dry_run_cost measures
    the prompts it lands in and discards them. estimated_codebase_chars is
    what decides that length, so the content would be read and thrown away.
    """
    return "x" * chars


def estimate_dry_run_cost(repo_path, instructions, provider, model, chapter_guess=DRY_RUN_CHAPTER_GUESS,
                          codebase_budget=CODEBASE_BUDGET):
    """Estimate the cost of a real run without calling any LLM. Input tokens
    use a chars/4 heuristic; output tokens assume every call hits the
    configured max-output cap (a worst-case upper bound, not a typical case)."""
    max_out = max_output_tokens()

    # Reuses SmartCrawl's own prep() for the file-selection prompt instead of
    # rebuilding its preview-manifest logic here -- one source of truth for
    # what that prompt looks like.
    crawl_state = {"repo_path": repo_path}
    select_prompt, _files, _root = SmartCrawl().prep(crawl_state)

    sized = estimated_codebase_chars(_files, _root, codebase_budget,
                                     target=crawl_state.get("target_files_used"))
    codebase = _codebase_preview_text(sized.likely)
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
    # Whether a real run would be refused before its first call. Measured with
    # the guard's own divisor rather than the chars/4 one above, since the
    # point is to predict that guard's verdict, not to price the run.
    ceiling = input_ceiling(provider, model)
    # Sized from the most a run could send, not the likely amount. The cost
    # line wants the expectation; this wants the ceiling, because a guard that
    # under-warns is the one that stays quiet on the run it exists to catch.
    headroom = sized.most - sized.likely
    largest_prompt_tokens = int((max(len(p) for p in prompts) + headroom) / CHARS_PER_TOKEN)
    estimated_output_tokens_worst_case = max_out * len(prompts)

    low_usage = {"input_tokens": estimated_input_tokens, "output_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_tokens": 0}
    high_usage = {"input_tokens": estimated_input_tokens, "output_tokens": estimated_output_tokens_worst_case,
                  "cache_read_tokens": 0, "cache_write_tokens": 0}

    return {
        "provider": provider, "model": model, "chapter_guess": chapter_guess,
        "codebase_budget": codebase_budget,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens_worst_case": estimated_output_tokens_worst_case,
        "cost_low": cost_for(provider, model, low_usage),
        "cost_high": cost_for(provider, model, high_usage),
        "input_ceiling": ceiling,
        "largest_prompt_tokens": largest_prompt_tokens,
        "readable_files": sized.readable,
        "previewed_files": sized.previewed,
    }


def format_dry_run_summary(estimate):
    if estimate["cost_low"] is None or estimate["cost_high"] is None:
        cost_line = "unknown (no pricing for this model)"
    else:
        cost_line = f"${estimate['cost_low']:.4f} - ${estimate['cost_high']:.4f}"
    return (
        "Estimated cost (dry run)\n"
        f"Assumes ~{estimate['chapter_guess']} chapters (actual count depends on the repo)\n"
        f"Codebase budget: {estimate['codebase_budget']:,} chars\n"
        f"Estimated cost:  {cost_line}\n"
        f"Estimated usage: ~{estimate['estimated_input_tokens']} input tokens, "
        f"up to ~{estimate['estimated_output_tokens_worst_case']} output tokens\n"
        "Note: this estimate does not account for prompt caching -- a real run "
        "reuses the same codebase block across calls, so actual cost is often "
        "lower than the low end shown here.\n"
        "The codebase figure models the files a run sends rather than the whole "
        "repository, but which files the model picks is not knowable in advance. "
        "Against five recorded runs it landed between 0.7x and 2.3x the real "
        "bundle."
        + _dry_run_unreadable_note(estimate)
        + _dry_run_refusal_note(estimate)
    )


def _dry_run_unreadable_note(estimate):
    """Whether the codebase block would be empty or nearly so.

    A run is not refused for this: prep's manifest falls back to an empty
    preview, the model picks indices off it, post skips every file it cannot
    read, and Analyze, Relate and every chapter call go out against an empty
    codebase. The user pays the quoted figure for a tour built from nothing,
    and no other line here says so.
    """
    readable = estimate.get("readable_files")
    previewed = estimate.get("previewed_files")
    if readable is None or previewed is None or readable == previewed:
        return ""
    if readable == 0:
        return (f"\nNone of the {previewed} source files here could be read, so a "
                "real run would send an empty codebase to every call and pay for it.")
    return (f"\nOnly {readable} of {previewed} source files could be read, so the "
            "figure above rests on that much of the repository.")


def _dry_run_refusal_note(estimate):
    """Whether a real run would be refused before it spent anything. Without
    this the one command whose job is to say what a run will do stays silent
    about the run not happening at all (coderay-8vk)."""
    ceiling = estimate.get("input_ceiling")
    largest = estimate.get("largest_prompt_tokens", 0)
    if ceiling is None:
        return ("\nNo input ceiling is recorded for this model, so a prompt too "
                "large for it would be refused by the provider rather than "
                "caught before the call.")
    if largest > ceiling:
        return (f"\nThis run would be refused before its first call: its largest "
                f"prompt is about {largest:,} tokens, over {estimate['model']}'s "
                f"{ceiling:,}-token input ceiling. Lower --codebase-budget.")
    return ""


def default_output_dir(repo_path, instructions):
    """Keyed on both repo name and lens, so re-running with a different
    --instructions writes to a separate directory instead of colliding with
    (and leaving orphaned chapter files from) a prior run's output. Anchored
    on the current working directory, not this file's location, so it lands
    in the same place whether crawl is run from an editable checkout or
    installed as a tool."""
    name = os.path.basename(os.path.abspath(repo_path))
    return os.path.join(os.getcwd(), "output", f"{name}-{instructions}-tour")
