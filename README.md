# Coderay

> Point it at any repo. Get back a multi-chapter tutorial with diagrams, cross references, and a learning order.

## What this ships

Packages a pipeline as a PocketFlow workflow so you get retry and clean node boundaries for free, but every node maps one to one to a function in the chapter.

- [`workflow/`](workflow/). Four nodes: smart crawl, analyze, relate, write chapters. The three that parse structured YAML retry bad output internally (`utils.yaml_call`); `WriteChapters` uses PocketFlow's `Node(max_retries=3)` since it calls the LLM directly.
- [`workflow/prompts/`](workflow/prompts/). The four prompts the chapter teaches. One file each.
- [`workflow/instructions/`](workflow/instructions/). Four swappable lenses (the chapter's punchline). Same pipeline, different output.
- [`skill/CODEBASE-TOUR.md`](skill/CODEBASE-TOUR.md). The agent equivalent.

## Quickstart

```bash
pip install -e .            # or: pip install -e ".[openai,gemini]" for those providers
cp .env.example .env        # fill in the one key you need, see .env.example for all options
export GEMINI_API_KEY=...   # or ANTHROPIC_API_KEY / OPENAI_API_KEY

python -m workflow path/to/repo   # or just: coderay path/to/repo
```

If the run fails partway through (a bad LLM response after retries, a network error), the files, abstractions, and chapters completed so far are written to `run_state.json` in the target output directory — useful for figuring out how far it got without rerunning the whole pipeline.

Output:

```bash
  Selected 20 files (280,023 chars)
  Found 8 abstractions
  Found 13 relationships
  Chapter 1/8: Tokenizer
  Chapter 2/8: GPT
  Chapter 3/8: COMPUTE_DTYPE
  ...

Wrote tour to ../output/nanochat-tour/
  Open ../output/nanochat-tour/index.html in a browser
```

You get back:

```text
output/nanochat-tour/
├── index.md            # mermaid diagram + chapter links
├── index.html          # same, browser ready, links to chapter HTML
├── 01_tokenizer.md     # plus 01_tokenizer.html
├── 02_gpt.md           # plus 02_gpt.html
├── 03_compute_dtype.md
└── ...
```

## Swap the lens

Same pipeline. Same code. Different `workflow/instructions/` file. Different output entirely.

```bash
python -m workflow path/to/repo --instructions architecture-review
python -m workflow path/to/repo --instructions security-audit
python -m workflow path/to/repo --instructions onboarding-guide
```

| Lens                          | What you get back                                                                         |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| `beginner-tutorial` (default) | Analogies, code blocks under 10 lines, "what happens when you close a tab" style openings |
| `architecture-review`         | Design decisions, alternatives, what breaks under load, technical debt                    |
| `security-audit`              | Trust boundaries, validation gaps, blast radius                                           |
| `onboarding-guide`            | First week TODO list, what to touch and avoid, real shell commands                        |

## How it works

```mermaid
flowchart LR
    crawl[SmartCrawl] --> analyze[Analyze]
    analyze --> relate[Relate]
    relate --> write[WriteChapters]
```

1. **SmartCrawl** (§3.2 of the book). Two phases. First filter by extension and skip the obvious noise (`tests/`, `docs/`, lock files, anything over 500 KB). Then build a preview manifest (first ~N chars of each remaining file) and ask the LLM to pick the 0.1 to 2 percent that actually matter. Uses the four selection rules from [`workflow/prompts/select-files.md`](workflow/prompts/select-files.md).
2. **Analyze** (§3.3). One LLM call. Returns YAML: 5 to 10 abstractions with analogies, plus a learning order.
3. **Relate** (§3.3). One LLM call. Returns edges between abstractions.
4. **WriteChapters** (§3.3). NOT a batch. Loops through chapters in learning order, passing every previous chapter forward as context. That's what makes the output read like a tutorial instead of a pile of disconnected pages.

The chapter writing step is sequential on purpose. Parallel batching loses the cross references and analogy reuse that make the tutorial coherent.

## Example output

One real tour, generated end to end against [karpathy/micrograd](https://github.com/karpathy/micrograd) (`output/` is gitignored, so this isn't checked in — run the quickstart above to get your own):

| Tour             | Files selected | Chars selected | Abstractions | Relationships | Chapters |
| ---------------- | -------------- | -------------- | ------------ | ------------- | -------- |
| `micrograd-tour` | 3              | 7,784          | 10           | 12            | 10       |

Each tour contains one markdown and one HTML file per abstraction, plus an `index.html` with the mermaid architecture diagram and chapter list. The chapter HTML files render code blocks, tables, and mermaid sequence diagrams cleanly.

## Development

```bash
pip install -e .
python -m pytest tests/ -v
```

CI (`.github/workflows/tests.yml`) runs the same suite on every push and PR.
