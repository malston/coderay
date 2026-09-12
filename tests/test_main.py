import os

import pytest
import subprocess
import sys
from importlib.metadata import version

from crawl.analyses.tour.render import (
    available_lenses,
    build_mermaid,
    build_related_links,
    default_output_dir,
    estimate_dry_run_cost,
    estimated_codebase_chars,
    format_dry_run_summary,
    format_session_summary,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)
from crawl.analyses.tour import render as render_theme
from crawl.analyses.tour.nodes import slug


def test_version_flag_prints_installed_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"crawl {version('crawl')}"


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


def test_the_tour_opts_back_into_markdown_images():
    """A deliberate divergence from crawl.core.render, which disables images
    because one is a beacon: `![x](https://host/p?leak=...)` becomes a live
    <img> that fires on page open, an egress channel from repo text via a
    prompt-injected model (coderay-q2r.53).

    The tour builds its parser with image=True, on the judgment that a reading
    document should show the diagrams a README embeds.

    That is an accepted risk, not an absent one. Tour prose is LLM output over
    the target repo's own files, so a prompt-injected model can emit an image
    whose URL carries repo text, and it fetches when the page opens. What
    bounds it: the reader is the operator who ran the tour, the output is a
    local file rather than something served, and no credential is in scope.
    Revisit the trade if any of those three stop being true.

    Pinned in both directions, so turning it off is a decision someone makes
    rather than a flip nobody notices.
    """
    out = md_to_html("![a diagram](https://example.com/d.png?who=me)")
    assert "<img" in out, "the tour no longer renders images; was that deliberate?"
    from crawl.core.render import markdown_parser
    assert "<img" not in markdown_parser().render("![a](https://example.com/d.png)"), (
        "core renders images too, so the tour is not diverging")


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


def test_chapter_link_rewrite_matches_crawl_nodes_filename_convention(tmp_path):
    # Regression for coderay-e06: crawl.analyses.tour.nodes generates chapter filenames via
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
        "cost_low": 0.01, "cost_high": 0.05, "codebase_budget": 1_000_000,
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
        "cost_low": None, "cost_high": None, "codebase_budget": 1_000_000,
    }
    out = format_dry_run_summary(estimate)
    assert "unknown" in out


def _dry_run_env(tmp_path, **extra):
    """A subprocess environment with every knob this project reads cleared, so a
    developer's shell cannot leak into the run, plus any values the test sets."""
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "config"))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER", "CODEBASE_BUDGET"):
        env.pop(var, None)
    env.update(extra)
    return env


def _one_file_repo(tmp_path):
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    return repo


def test_dry_run_flag_estimates_without_creating_the_output_directory(tmp_path, monkeypatch):
    repo = _one_file_repo(tmp_path)
    out_dir = tmp_path / "out"
    env = _dry_run_env(tmp_path, ANTHROPIC_API_KEY="test-key")

    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "tour", str(repo), "--dry-run", "--out", str(out_dir)],
        capture_output=True, text=True, env=env, check=True,
    )

    assert "Estimated cost (dry run)" in result.stdout
    assert not out_dir.exists()


def test_dry_run_flag_works_with_no_llm_key_configured(tmp_path):
    # The spec requires --dry-run to need no API key at all -- it falls back
    # to the anthropic default when resolve_provider_and_model() can't find one.
    repo = _one_file_repo(tmp_path)
    env = _dry_run_env(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "tour", str(repo), "--dry-run"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0
    assert "Estimated cost (dry run)" in result.stdout


# coderay-5wu.15: the dry run sizes the codebase with the budget it is handed
# and reports it, so a user can see what --codebase-budget would change.
def test_estimate_dry_run_cost_honours_the_codebase_budget(tmp_path):
    _make_repo_files(tmp_path, count=5, size=500)
    small = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "anthropic", "claude-sonnet-5",
                                  codebase_budget=100)
    large = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "anthropic", "claude-sonnet-5",
                                  codebase_budget=100_000)
    assert small["codebase_budget"] == 100 and large["codebase_budget"] == 100_000
    assert small["estimated_input_tokens"] < large["estimated_input_tokens"]


def test_format_dry_run_summary_reports_the_codebase_budget():
    estimate = {
        "provider": "anthropic", "model": "claude-sonnet-5", "chapter_guess": 8,
        "estimated_input_tokens": 1000, "estimated_output_tokens_worst_case": 5000,
        "cost_low": 0.01, "cost_high": 0.05, "codebase_budget": 2_000_000,
    }
    assert "Codebase budget: 2,000,000 chars" in format_dry_run_summary(estimate)


def test_dry_run_flag_reports_the_codebase_budget_it_would_use(tmp_path):
    repo = _one_file_repo(tmp_path)
    env = _dry_run_env(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "crawl.cli", "tour", str(repo), "--dry-run", "--codebase-budget", "2000000"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Codebase budget: 2,000,000 chars" in result.stdout


# coderay-3le. The dry-run estimator sized the codebase from every readable
# file, where a real run sends the ~20 the model picks, each wrapped in a
# header block. Measured against five past runs whose selections are on
# record, that overstated by 2.6x to 5.8x on repos under the budget.
def _repo(tmp_path, sizes):
    """A repo of len(sizes) python files, sizes[i] chars each, as the
    estimator receives it: the files SmartCrawl.prep previewed, and the root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(sizes):
        (tmp_path / f"mod_{i:03d}.py").write_text("x" * n, encoding="utf-8")
    from crawl.analyses.tour.nodes import SmartCrawl
    _prompt, files, root = SmartCrawl().prep({"repo_path": str(tmp_path)})
    return files, root


def test_the_estimate_sizes_the_files_a_run_sends_not_every_file(tmp_path):
    """100 files, of which SmartCrawl targets 20. Sizing all 100 is the bug."""
    repo = _repo(tmp_path, [1000] * 100)
    chars, _most = estimated_codebase_chars(*repo, budget=10_000_000)
    every_file = 100 * 1000
    assert chars < every_file / 2, (
        f"{chars:,} is closer to all 100 files ({every_file:,}) than to the 20 sent")


def test_the_estimate_counts_the_header_each_file_is_wrapped_in(tmp_path):
    """SmartCrawl.post wraps every file in a rule, its path and another rule.
    On twenty small files that chrome is most of the bundle."""
    repo = _repo(tmp_path, [10] * 100)
    chars, _most = estimated_codebase_chars(*repo, budget=10_000_000)
    assert chars > 20 * 100, f"{chars:,} looks like bare text with no block chrome"


def test_the_estimate_stops_at_the_budget(tmp_path):
    """The real bundle stops there, so an estimate above it is unreachable."""
    repo = _repo(tmp_path, [50_000] * 100)
    likely, _most = estimated_codebase_chars(*repo, budget=200_000)
    assert likely <= 200_000


def test_the_estimate_carries_the_measured_skew(tmp_path):
    """The model picks architecturally important files, which ran 0.8x to 2.4x
    a size-blind pick over the four uncapped runs measured. Without the
    correction the estimate understated three of those four."""
    repo = _repo(tmp_path, [1000] * 100)
    chars, _most = estimated_codebase_chars(*repo, budget=10_000_000)
    # The block chrome alone puts the figure above the bare text, so compare
    # against twenty whole blocks: only the skew can carry it past that.
    one_block = 1000 + len("mod_000.py") + render_theme._BLOCK_CHROME
    assert chars > 20 * one_block * 1.5, (
        f"{chars:,} is one skew-free bundle of {20 * one_block:,}")


def test_an_empty_repo_estimates_nothing(tmp_path):
    assert estimated_codebase_chars([], str(tmp_path), budget=1000) == (0, 0)


def test_the_estimate_tracks_the_real_bundle_on_a_recorded_run(tmp_path):
    """A repo shaped like intapp-ai-pdlc, the closest of the measured runs:
    270 files, 20 picked, a real bundle of 384,428 chars. The estimate should
    land within a factor of two of that rather than the 2.6x it did."""
    repo = _repo(tmp_path, [9_500] * 270)
    chars, _most = estimated_codebase_chars(*repo, budget=1_000_000)
    real = 384_428
    assert real / 2 < chars < real * 2, f"{chars:,} is not within 2x of {real:,}"


def test_a_repo_smaller_than_the_target_is_not_sized_as_if_it_were_bigger(tmp_path):
    """SmartCrawl's target has a floor of 20, which on a seven-file repository
    asks for more files than exist. Sizing 20 of them put a measured run from
    1.2x to 7.5x before the count was capped at what the model was shown."""
    repo = _repo(tmp_path, [1000] * 7)
    chars, _most = estimated_codebase_chars(*repo, budget=10_000_000)
    every_file = 7 * (1000 + 130)
    assert chars < every_file * 1.5, (
        f"{chars:,} sizes more than the {7} files that exist ({every_file:,})")


def test_a_repo_the_model_cannot_select_within_carries_no_skew(tmp_path):
    """Skew is what choosing costs. Where the target covers every file there is
    no choice, and applying it inflates the one case this can get exact."""
    small, _most = estimated_codebase_chars(*_repo(tmp_path / "s", [1000] * 5), budget=10_000_000)
    assert small < 5 * (1000 + 130) * 1.5, f"{small:,} applies skew with nothing to choose"


def test_the_ceiling_is_never_below_what_a_run_could_send(tmp_path):
    """The refusal note is sized from the second figure. An average sits under
    the real bundle whenever the model picks heavier-than-mean files, so a
    guard reading the average stays quiet on exactly the run it exists to
    catch (coderay-8vk). A few large files among many small ones is the shape
    that separates the two."""
    files, root = _repo(tmp_path, [2_000] * 200 + [150_000] * 20)
    likely, most = estimated_codebase_chars(files, root, budget=10_000_000)
    whole_repo = sum(len(p.read_text(encoding="utf-8")) for p in tmp_path.glob("*.py"))
    assert most >= likely, f"the ceiling {most:,} is under the expectation {likely:,}"
    assert most >= whole_repo, (
        f"the ceiling {most:,} is under the whole repository {whole_repo:,}, "
        "which a run could send in full")


def test_the_ceiling_allows_for_the_block_that_crosses_the_budget(tmp_path):
    """SmartCrawl.post tests the budget before appending, so the last file goes
    in after the total has already reached it. A ceiling clamped exactly at the
    budget would be under the real bundle by up to one block."""
    files, root = _repo(tmp_path, [40_000] * 60)
    _likely, most = estimated_codebase_chars(files, root, budget=100_000)
    assert most > 100_000, f"the ceiling {most:,} cannot be reached past the budget"


def test_the_dry_run_prices_the_files_a_run_sends_not_the_repository(tmp_path):
    """The estimator is only worth having if the number a user reads uses it.

    Every other test here calls estimated_codebase_chars directly, so all of
    them pass with the function computed and then ignored -- which is the whole
    defect, reintroduced one layer up.
    """
    for i in range(100):
        (tmp_path / f"mod_{i:03d}.py").write_text("x" * 1000, encoding="utf-8")
    estimate = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial",
                                     "anthropic", "claude-sonnet-5")
    # The codebase block lands in ten of the eleven prompts, priced at chars/4.
    every_file = 100 * 1000 * 10 // 4
    assert estimate["estimated_input_tokens"] < every_file, (
        f"{estimate['estimated_input_tokens']:,} tokens is repository-sized, "
        f"not run-sized (every file would be about {every_file:,})")


def test_the_estimate_matches_the_bundle_smart_crawl_actually_builds(tmp_path):
    """Under the target floor the model picks every file, so the estimate is
    not a guess: it is arithmetic, and SmartCrawl.post is the answer key.

    The sizes vary on purpose. A uniform repository makes the mean equal to
    every file, which hides whether the population term is a mean at all.
    """
    from crawl.analyses.tour.nodes import SmartCrawl
    sizes = [100, 5_000, 300, 40_000, 900, 12, 7_777]
    files, root = _repo(tmp_path, sizes)
    shared = {"repo_path": root, "codebase_budget": 10_000_000}
    SmartCrawl().post(shared, None, ([str(p) for p in files], ""))
    real = len(shared["codebase"])

    likely, most = estimated_codebase_chars(files, root, budget=10_000_000)
    # The estimator charges one joiner to every block; the bundle has one
    # between each pair, so it sits a couple of characters per file above.
    assert abs(likely - real) <= 2 * len(sizes), (
        f"estimate {likely:,} against a real bundle of {real:,}")
    assert most >= real, f"the ceiling {most:,} is under the real bundle {real:,}"


def test_choosing_files_is_what_the_skew_prices(tmp_path):
    """Same mean file, same path length, same target of twenty. The only
    difference is whether the model had a hundred files to choose among or
    exactly twenty, which is what the skew is for."""
    chooses, _ = estimated_codebase_chars(*_repo(tmp_path / "many", [1000] * 100),
                                          budget=10_000_000)
    cannot, _ = estimated_codebase_chars(*_repo(tmp_path / "few", [1000] * 20),
                                         budget=10_000_000)
    assert chooses == pytest.approx(cannot * render_theme.SELECTION_SKEW, rel=0.01)


def test_the_dry_run_states_the_band_it_was_measured_at(tmp_path):
    """The only place a user learns the figure has an error bar."""
    for i in range(30):
        (tmp_path / f"m_{i:02d}.py").write_text("x" * 500, encoding="utf-8")
    out = format_dry_run_summary(
        estimate_dry_run_cost(str(tmp_path), "beginner-tutorial",
                              "anthropic", "claude-sonnet-5"))
    assert "0.7x and 2.3x" in out, "the measured band is not stated to the reader"


def test_the_refusal_note_speaks_for_a_run_the_average_would_hide(tmp_path):
    """A few large files among many small ones: the model picks the large ones,
    so the real bundle runs well past a mean-based figure. Sizing the refusal
    check from the expectation rather than the ceiling left this run silent."""
    for i in range(200):
        (tmp_path / f"small_{i:03d}.py").write_text("x" * 5_000, encoding="utf-8")
    for i in range(20):
        (tmp_path / f"big_{i:02d}.py").write_text("x" * 150_000, encoding="utf-8")
    out = format_dry_run_summary(
        estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "anthropic",
                              "claude-sonnet-5", codebase_budget=3_000_000))
    assert "would be refused" in out, "the guard stayed quiet on a run that cannot start"


def test_the_population_term_is_a_mean_and_not_the_largest_file(tmp_path):
    """With more files than the target, the ceiling no longer clamps the figure,
    so the population term is what decides it. One huge file among small ones
    separates a mean from a maximum; a uniform repository cannot."""
    files, root = _repo(tmp_path, [1_000] * 99 + [400_000])
    likely, _most = estimated_codebase_chars(files, root, budget=100_000_000)
    from_the_mean = 20 * ((99 * 1_000 + 400_000) / 100) * render_theme.SELECTION_SKEW
    assert likely == pytest.approx(from_the_mean, rel=0.05), (
        f"{likely:,} is not twenty mean files; the largest would give "
        f"{20 * 400_000 * render_theme.SELECTION_SKEW:,.0f}")


def test_the_skew_is_the_value_that_was_measured():
    """Pinned to the number, not to itself. A retune is a deliberate edit that
    shows in a diff, and the band the dry run quotes has to be re-measured
    with it."""
    assert render_theme.SELECTION_SKEW == 2.0
