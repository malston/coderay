# Porting the six sibling analyses into crack (coderay-q2r)

## Problem

`crack` ships one analysis, `tour`. A sibling fork --
`github.com/malston/Crack-Any-Codebase-with-AI`, branch `feat/unified-cli`,
pinned at `75ec7c4` -- carries six more: product-intent, git-history, schema,
interfaces, architecture, backend. Each has its own crawl, node graph, and
renderer.

The epic was filed on the assumption that these would be hand-ported from the
`ch05-ch10` chapter directories. They do not need to be. That branch already
contains a finished unified `src/crack/` package: all six analyses, a shared
card-family render engine, a lazy registry, `crack all` with a landing page,
and byte-for-byte parity tests against each chapter's original renderer. 4,532
lines across 32 modules and 16 test files.

So the work is a merge, not a rewrite.

## Goals

- Each of the six lands as a `crack <name> <repo>` subcommand, registered in
  `crack.analyses.ANALYSES`.
- The four card-family analyses (backend, architecture, interfaces, schema)
  share one render engine, ported verbatim from the sibling.
- The two bespoke analyses (git-history, product-intent) keep their hand-built
  renderers.
- Each ported analysis is covered by a test proving it reproduces the sibling's
  output for a fixed input.

## Non-goals (this epic)

- Reconciling the ported analyses against coderay's own improvements: the
  `yaml_call` varied-tail retry, the deterministic import graph, cost tracking,
  the staleness disclaimer, and failure-state dumps. That is coderay-dr8, and
  it is blocked on this epic finishing. Ported analyses stay close to their
  source behavior until then.
- `crack all` and its landing page (`core/index.py` in the sibling). Deferred
  with the same reasoning the CLI restructure spec used.
- `call_image` and the image-generation path, which only product-intent needs.
  It arrives with that analysis, not before.

## Decision: keep the per-module `run(args)` interface

The two projects orchestrate differently.

The sibling's analysis modules expose `NAME`, `build_flow`, and
`init_shared(args, out_dir)`, and a generic `core/runner.run_analysis()` does
the rest: mkdir, apply `ENV_DEFAULTS`, run the flow, write `index.md` and
`index.html`. 15 lines, one code path for all six.

The CLI restructure (coderay-8bg) instead gave each module its own
`run(args)` and `add_arguments(parser)`, with `cli.py` dispatching to
`ANALYSES[name].run(args)`. `tour` needs that: its `run()` handles a
`--dry-run` early exit, an `--instructions` lens that keys the output
directory, `ensure_priced`/`reset_usage` and a wall-clock session cost summary,
per-chapter output files beyond the two index files, a `generated_at`
staleness date threaded through every writer, and `dump_run_state` on failure.

Adopting the sibling's generic runner would mean growing it a pre-run hook, a
post-run hook, a cost wrapper, and a failure callback. The restructure spec
refused exactly that ("core/runner.py stays narrow ... generalize when a
second analysis actually needs it"), and the reconciliation it implies is
coderay-dr8's charter.

**Decision (2026-09-01, Mark):** keep 8bg's interface. The six ported analyses
share one `run_analysis(analysis, args)` helper in `crack/core/runner.py`, and
each module's `run()` is a thin call into it. `tour` is untouched.

The divergence this creates is confined to the orchestration layer, roughly
120 lines, and that is the layer least likely to change upstream. The ~4,000
lines that carry the actual analysis work -- the card engine, the nodes, the
crawls, the prompts -- come across verbatim either way, so future sibling
changes to them stay mergeable.

Revisit if `run_analysis` starts accumulating per-analysis special cases. All
six sibling analyses already share one code path, so it should not.

## What comes across

Into `crack/core/`, verbatim from the sibling except where noted:

| File          | Contents                                                                | Change on port                 |
| ------------- | ----------------------------------------------------------------------- | ------------------------------ |
| `render.py`   | `Section`, `Theme`, the card engine, `md`/`md_rich`/`esc`/`split_cards` | none                           |
| `overview.py` | `write_overview`                                                        | none                           |
| `nodes.py`    | `OverviewNode`                                                          | none                           |
| `env.py`      | `env_defaults` context manager                                          | none                           |
| `llm.py`      | gains `extract_mermaid`                                                 | added to existing file         |
| `runner.py`   | gains `run_analysis`                                                    | new function beside `run_flow` |

Into `crack/analyses/<name>/`, one directory per analysis: its `nodes.py`, its
crawl module, its `prompts/`, and an `__init__.py` carrying `SECTIONS`/`THEME`
(card family) or `render_html`/`render_markdown` (bespoke), plus the
`NAME`/`build_flow`/`add_arguments`/`init_shared`/`run` interface.

No new dependencies. `markdown-it-py`, which the card engine needs, is already
in coderay's dependency list.

## Conventions the port must respect

These are coderay's, and the sibling's code does not already follow them:

- **Prompt loading** goes through `importlib.resources.files(...)`, not
  `os.path.join(os.path.dirname(__file__), ...)`. coderay's `read_prompt`
  takes a Traversable and calls `(dir / name).read_text()`, so a plain string
  path fails.
- **Output directory** defaults to `<cwd>/output/<repo-name>-<analysis>`,
  matching `tour`'s `default_output_dir`, not the sibling's
  `output/<repo>/<analysis>`.
- **Packaging**: every new analysis package needs an entry in
  `[tool.setuptools] packages` and a `[tool.setuptools.package-data]` line for
  its `prompts/*.md`.
- **Untrusted input** from the target repo must be escaped before it reaches
  HTML or Mermaid output. The card engine's `esc()` and markdown-it's
  `html: False` cover this; any new rendering path must not bypass them.

## Testing

The sibling's parity tests load each chapter's `render.py` off disk from
`ch10-backend/workflow/` and diff HTML byte-for-byte with an explicit list of
deliberate unifications. coderay has no chapter directories, so those tests
cannot come across as written.

They also do not need to. That the engine reproduces each chapter's page is
already proven upstream, on the branch being ported from. What coderay needs to
prove is narrower: that the port is faithful to its source.

So each analysis gets a golden-output test. A small fixture `shared` dict, the
kind a real run would produce, is rendered by the sibling's own renderer once;
the resulting `index.html` and `index.md` are committed under
`tests/fixtures/`. The ported code must reproduce them byte for byte. A drift
in the card engine, a theme value, or a section definition fails the test.

Unit tests cover the crawl modules directly against the existing
`tests/fixtures/toy_repo/`, with no LLM involved. LLM calls stay faked at the
`call_llm`/`yaml_call` boundary, per the existing convention. No test needs
network or an API key.
