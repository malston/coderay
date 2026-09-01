# Coderay

Coderay generates a multi-chapter tour of a codebase: a written walkthrough with diagrams, cross-references between chapters, and a suggested reading order. Point it at a repo and it produces a set of HTML/Markdown pages explaining how the code works.

## What this ships

A four-stage pipeline, implemented as a [PocketFlow](https://github.com/The-Pocket/PocketFlow) workflow (retries and node isolation come from the framework; each node maps to one pipeline stage):

- [`src/crack/analyses/tour/`](src/crack/analyses/tour/) — the `tour` analysis: SmartCrawl, ExtractGraph, Analyze, Relate, WriteChapters. SmartCrawl, Analyze, and Relate parse structured YAML output and retry on a bad response (`crack.core.yaml_call`); WriteChapters calls the LLM directly and retries via PocketFlow's own `Node(max_retries=3)`.
- [`src/crack/analyses/tour/prompts/`](src/crack/analyses/tour/prompts/) — the prompt template each stage sends to the LLM, one file per stage.
- [`src/crack/analyses/tour/instructions/`](src/crack/analyses/tour/instructions/) — four swappable output styles (see "Swap the output style" below). Same pipeline, different framing for the same chapters.
- [`skill/CODEBASE-TOUR.md`](skill/CODEBASE-TOUR.md) — the same analysis packaged as an agent skill.

## Quickstart

```bash
pip install -e .            # or: pip install -e ".[openai,gemini]" for those providers
cp .env.example .env        # fill in the one key you need, see .env.example for all options
export GEMINI_API_KEY=...   # or ANTHROPIC_API_KEY / OPENAI_API_KEY

crack tour path/to/repo
```

If a run fails partway through (a bad LLM response after retries, a network error), the files, abstractions, and chapters completed so far are written to `run_state.json` in the target output directory, so you can see how far it got without rerunning the whole pipeline.

Example output:

```bash
  Selected 20 files (280,023 chars)
  Found 8 abstractions
  Found 13 relationships
  Chapter 1/8: Tokenizer
  Chapter 2/8: GPT
  Chapter 3/8: COMPUTE_DTYPE
  ...

Wrote tour to ../output/nanochat-beginner-tutorial-tour/
  Open ../output/nanochat-beginner-tutorial-tour/index.html in a browser
```

The output directory name includes the repo name and the output style, so running the same repo with a different `--instructions` value writes to a separate directory instead of overwriting the previous run:

```text
output/nanochat-beginner-tutorial-tour/
├── index.md            # mermaid diagram + chapter links
├── index.html          # same, browser ready, links to chapter HTML
├── 01_tokenizer.md     # plus 01_tokenizer.html
├── 02_gpt.md           # plus 02_gpt.html
├── 03_compute_dtype.md
└── ...
```

## Swap the output style

Same pipeline and code, driven by a different file under `src/crack/analyses/tour/instructions/`. Set `--instructions` to change what the chapters focus on:

```bash
crack tour path/to/repo --instructions architecture-review
crack tour path/to/repo --instructions security-audit
crack tour path/to/repo --instructions onboarding-guide
```

| Style                         | What you get                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------- |
| `beginner-tutorial` (default) | Analogies, code blocks under 10 lines, plain explanations of what each part does |
| `architecture-review`         | Design decisions, alternatives considered, failure modes, technical debt         |
| `security-audit`              | Trust boundaries, input validation gaps, blast radius of a compromise            |
| `onboarding-guide`            | A first-week checklist: what to touch, what to avoid, real shell commands        |

## Estimate cost before you run it

```bash
crack tour path/to/repo --dry-run
```

`--dry-run` makes no network calls, needs no API key, and writes nothing to disk. It estimates the size of the prompts a real run would send (file selection, abstraction analysis, relationships, and one chapter prompt repeated for an estimated chapter count) and prints a cost range:

```text
Estimated cost (dry run)
Assumes ~8 chapters (actual count depends on the repo)
Estimated cost:  $0.0123 - $0.1456
Estimated usage: ~12345 input tokens, up to ~131072 output tokens
Note: this estimate does not account for prompt caching -- a real run
reuses the same codebase block across calls, so actual cost is often
lower than the low end shown here.
```

The low end of the range assumes zero output tokens; the high end assumes every call hits the configured max-output limit. Treat the high end as a worst case, not a typical cost. If the selected model has no pricing entry, the range shows `unknown (no pricing for this model)` instead of a number.

The estimate also can't account for prompt caching, since it never makes a real LLM call. A real run reuses the same codebase text across the Analyze, Relate, and WriteChapters calls, so part of what the estimate treats as full-price input ends up billed as cheaper cache reads. On a repo where caching kicks in heavily, the actual cost reported after a real run can come in below this estimate's low end.

A real run (without `--dry-run`) prints a `Session` summary at the end with the actual token counts and cost, based on the usage each LLM call reported.

### Pricing overrides

Built-in pricing covers the default model for each provider. For any other model, crack prompts you once, interactively, for $/1M token pricing, and saves it to `~/.config/crack/pricing.json`. That file is yours to edit directly; an entry there always takes priority over the built-in pricing table. Format:

```json
{
  "openai:gpt-6-preview": {
    "input": 3.0,
    "output": 15.0,
    "cache_read": 0.3,
    "cache_write": 0.0
  }
}
```

## How it works

```mermaid
flowchart LR
    crawl[SmartCrawl] --> extract[ExtractGraph] --> analyze[Analyze]
    analyze --> relate[Relate]
    relate --> write[WriteChapters]
```

1. **SmartCrawl.** Two phases. First, filter files by extension and skip obvious noise (`tests/`, `docs/`, lock files, anything over 500 KB). Then build a preview manifest — the first few hundred characters of each remaining file — and ask the LLM to select the roughly 0.1-2% of files that matter most, using the selection rules in [`src/crack/analyses/tour/prompts/select-files.md`](src/crack/analyses/tour/prompts/select-files.md).
2. **ExtractGraph.** No LLM call — deterministically parses each selected file's imports (Python/JS/TS) into `symbol_graph`, the edges Relate later checks against.
3. **Analyze.** One LLM call. Returns a YAML list of 5-10 abstractions, each with a short description, plus a suggested learning order.
4. **Relate.** One LLM call. Returns the relationships (edges) between those abstractions, each tagged `EXTRACTED` (backed by a real import edge between the abstractions' files, Python/JS/TS only) or `INFERRED` (LLM judgment). The mermaid diagram in `index.html` draws `EXTRACTED` edges solid, `INFERRED` edges dashed.
5. **WriteChapters.** Not batched. Writes chapters one at a time, in learning order, passing every previously written chapter forward as context. This keeps the chapters consistent with each other instead of reading like unrelated pages.

WriteChapters runs sequentially on purpose: running it in parallel would lose the cross-chapter context that keeps the tour coherent.

## Example output

One real tour, generated end to end against [karpathy/micrograd](https://github.com/karpathy/micrograd) (`output/` is gitignored, so this isn't checked in — run the quickstart above to generate your own):

| Tour             | Files selected | Chars selected | Abstractions | Relationships | Chapters |
| ---------------- | -------------- | -------------- | ------------ | ------------- | -------- |
| `micrograd-tour` | 3              | 7,784          | 10           | 12            | 10       |

Each tour contains one Markdown and one HTML file per abstraction, plus an `index.html` with the architecture diagram and chapter list. The chapter HTML pages render code blocks, tables, and Mermaid diagrams.

## Development

```bash
pip install -e .
python -m pytest tests/ -v
```

CI (`.github/workflows/tests.yml`) runs the same test suite on every push and pull request.
