# Unified CLI restructure: coderay becomes crack (coderay-8bg)

## Problem

coderay ships one pipeline (`SmartCrawl -> ExtractGraph -> Analyze -> Relate ->
WriteChapters`) behind `python -m workflow`/the `coderay` console script, with
swappable `--instructions` prompt lenses. A sibling project,
`Crack-Any-Codebase-with-AI`, has six _additional_ analyses (ch05-ch10:
product-intent, git-history, schema, interfaces, architecture, backend) --
each its own crawl, node graph, and renderer, not a lens on one pipeline. Its
own `unified-cli-design.md` collapses those six into one installable package
with one CLI (`crack`).

This project wants the same shape: bring the six analyses into coderay as new
subcommands (see coderay-q2r), reconcile them against coderay's own
improvements (coderay-dr8), and add ch04-agent's interactive prompts as
sibling skill files (coderay-buf). All three depend on this one landing
first: a package restructure that turns coderay's single pipeline into one
subcommand among several, under the `crack` name.

## Goals

- One console script, `crack`, dispatching to named analysis subcommands.
  Today: `crack tour <repo>`. Tomorrow (coderay-q2r): `crack backend <repo>`,
  etc.
- `src/crack/core/` holds plumbing any analysis can share (LLM calls, prompt
  filling, YAML retry, crawling, pricing). `src/crack/analyses/tour/` holds
  everything specific to the existing pipeline.
- Full project rename: git repo, `pyproject.toml` project name, and docs all
  become `crack`. Confirmed distinct from the sibling project's own `crack`
  package -- they stay in separate venvs, so the console-script name
  collision this would otherwise cause is a non-issue.
- Clean break. No `python -m workflow`, no back-compat shim for the old
  `coderay <repo>` invocation.

## Non-goals (this iteration)

- Porting any of the six ch05-ch10 analyses (coderay-q2r).
- Deciding whether ported analyses inherit coderay's `yaml_call`
  retry/cache layer, the import graph, cost tracking, or the staleness
  disclaimer (coderay-dr8) -- there's only one analysis today, so nothing to
  reconcile yet.
- `crack all` (runs every analysis, writes a landing page). Meaningless with
  one analysis; introduced when coderay-q2r lands a second one.
- A generic per-analysis dry-run/cost-estimation interface. Today's
  estimator is tightly coupled to tour's specific node prompts; premature to
  design a shared shape before a second analysis exists to prove it out.
- Moving `graph/` (the tree-sitter import extractors) into `core/`. Only
  tour needs import-graph extraction today. Tracked as a follow-up
  (coderay-wy9) for whenever a second analysis needs the same capability.

## Package layout

```text
pyproject.toml              # package "crack", console script "crack"
src/crack/
  __init__.py
  cli.py                     # argparse: subcommand dispatch
  core/
    call_llm.py              # from coderay_utils/call_llm.py, import path only
    llm.py                   # read_prompt, fill, parse_yaml, yaml_call
    crawl.py                 # list_files, safe_read, defaults
    pricing.py                # cost_for, ensure_priced, get_price
    runner.py                 # flow.run(shared); dump run_state.json on failure
  analyses/
    __init__.py               # registry: name -> analysis module, lazy import
    tour/
      __init__.py              # NAME="tour", build_flow, add_arguments, init_shared
      nodes.py                  # SmartCrawl, ExtractGraph, Analyze, Relate, WriteChapters
      flow.py
      render.py                 # write_index_md/html, build_mermaid, chapter writing,
                                # dry-run cost estimate, session cost summary
      prompts/*.md
      instructions/*.md         # today's --instructions lenses become tour's own flag values
      graph/languages/*.py       # the Python/JS/TS import extractors (tour-only for now)
tests/                          # existing tests/, import paths updated to match
```

`coderay_utils/`, `workflow/`, and the dead top-level `utils/` (confirmed
empty -- only a stray `__pycache__`, nothing imports it) all go away. Their
live content moves under `src/crack/`; nothing gets duplicated.

## CLI dispatch and the runner split

```python
# cli.py
def main():
    parser = argparse.ArgumentParser(prog="crack")
    parser.add_argument("--version", action="version", ...)
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    for name, analysis in ANALYSES.items():   # today: just {"tour": ...}
        sub = subparsers.add_parser(name)
        sub.add_argument("repo_path")
        sub.add_argument("--out", default=None)
        analysis.add_arguments(sub)            # tour's --instructions, --dry-run
    args = parser.parse_args()
    ANALYSES[args.analysis].run(args)
```

`core/runner.py` stays narrow: it owns only what's genuinely generic across
any future analysis -- `flow.run(shared)`, and dumping `run_state.json` on an
unhandled failure. Everything else that today's `__main__.py` does (dry-run
cost estimation, the session cost summary, `--instructions` handling) is
tightly coupled to tour's specific node prompts and stays inside
`analyses/tour/render.py` rather than becoming a speculative shared
interface. Generalize when coderay-q2r's first real second analysis actually
needs it -- not before.

## Analysis-module interface (tour's shape)

Tour is the sole analysis for now, and it doesn't fit the sibling project's
card-family `SECTIONS`/`THEME` contract (that's built for six _different_
analyses sharing one card renderer; tour's chapter-based output -- mermaid
diagram, sequential chapters, cross-links -- is a different kind of report).
It uses the bespoke escape hatch instead, matching how the sibling design
already treats its two hand-built analyses (product-intent, git-history):

```python
NAME = "tour"
def build_flow() -> pocketflow.Flow
def add_arguments(parser) -> None      # --instructions, --dry-run
def init_shared(args, out_dir) -> dict
def run(args) -> None                   # orchestrates: init_shared, core.runner,
                                        # render.py's writers, cost summary
```

Tour also writes extra files beyond `index.md`/`index.html` (one `.md`/`.html`
pair per chapter). This already fits the sibling design's own allowance --
"analyses may write extra files into `out_dir` beyond `index.md` and
`index.html`" -- so no special-casing is needed for tour's multi-file output.

## Migration order

1. Rename the GitHub repo to `crack` (a real external action -- confirmed
   explicitly with Mark at execution time, not assumed from this design).
2. `pyproject.toml` skeleton: package name `crack`, `src` layout, console
   script `crack = crack.cli:main`.
3. Move `coderay_utils/*` -> `src/crack/core/*`: file moves and import-path
   updates, not a rewrite.
4. Move `workflow/graph/languages/` -> `src/crack/analyses/tour/graph/languages/`.
5. Move `workflow/nodes.py`, `flow.py`, `prompts/`, `instructions/` ->
   `src/crack/analyses/tour/`.
6. Split `workflow/__main__.py` into `cli.py` (thin dispatch) and
   `analyses/tour/render.py` (everything else it currently does).
7. Update `tests/` import paths to the new locations. Delete `workflow/`,
   `coderay_utils/`, and the dead `utils/`.
8. Update `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `AGENTS.md` for the
   new command and layout.

## Testing

TDD per step, matching the sibling design's own approach: each extraction
step lands with its test updated (import paths, not behavior) before moving
on, so the suite never sits broken for more than one step. No behavior
change is intended anywhere in this migration -- it's a pure restructure, so
every existing test should pass unmodified except for its imports. A final
end-to-end smoke run (`crack tour <fixture-repo>`) confirms the console
script works post-rename, matching the sibling design's own `test_smoke.py`
pattern (skipped without an API key).

## Decisions

- **Full project rename to `crack`**, not just the package/command --
  confirmed distinct from the sibling project's own `crack` package since
  they stay in separate venvs.
- **`core/runner.py` stays narrow** (just `flow.run` + failure dump); dry-run
  cost estimation and the session summary stay tour-specific until a second
  analysis proves out what should generalize.
- **`graph/` stays under `analyses/tour/`**, not `core/`, until a second
  analysis needs import-graph extraction (coderay-wy9 tracks revisiting
  this).
- **No `crack all`** in this iteration -- meaningless with one analysis.
- **Clean break**: no back-compat shim for `python -m workflow` or the old
  `coderay <repo>` invocation.
