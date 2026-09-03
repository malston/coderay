# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->

## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**

- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.

<!-- END BEADS INTEGRATION -->

## Build & Test

`make install`, `make test`, `make build`, and `make clean` cover the common dev loop via `uv`, matching CI (see `Makefile`). Equivalent raw commands, if you don't have `make`:

```bash
pip install -e .              # install this package (src/crack/) in editable mode
pip install -e ".[openai,gemini]"  # add optional provider SDKs as needed

python -m pytest tests/ -v    # run the test suite (no API key or network needed)
crack tour path/to/repo   # run the tour analysis end to end (needs an API key, see .env.example)
```

CI runs `pytest` on every push/PR via `.github/workflows/tests.yml`. To cut a release, bump `version` in `pyproject.toml`, tag it (e.g. `git tag v0.2.0 && git push origin v0.2.0`), and `.github/workflows/release.yml` builds the package and creates a GitHub Release with the sdist/wheel attached.

## Architecture Overview

Crack dispatches to seven analyses, each a PocketFlow pipeline:

**Tour** (five sequential nodes, `src/crack/analyses/tour/nodes.py`, wired in `src/crack/analyses/tour/flow.py`):

```text
SmartCrawl -> ExtractGraph -> Analyze -> Relate -> WriteChapters
```

- **SmartCrawl** walks the target repo (`src/crack/core/crawl.py`), builds a preview manifest, and asks the LLM which ~0.1-2% of files matter. Enforces `preview_budget` and `codebase_budget` so large repos can't blow the LLM's context window.
- **Analyze** / **Relate** / **WriteChapters** call the LLM via `crack.core.call_llm` and parse its YAML output via `crack.core.yaml_call`, which retries with a varied prompt on bad output (the retry-safe path -- don't reintroduce a local prompt-parsing loop that bypasses it, see the Rules doc).
- `src/crack/analyses/tour/render.py` renders the analysis's output (`shared` dict, typed as `PipelineState` in `src/crack/analyses/tour/nodes.py`) to markdown + HTML.
- `src/crack/analyses/tour/prompts/*.md` are the four LLM prompt templates; `src/crack/analyses/tour/instructions/*.md` are swappable output lenses (`--instructions <name>`), auto-discovered from the directory -- adding a lens is just adding a file.

**Backend** (five sequential nodes: four in `src/crack/analyses/backend/nodes.py` plus the shared `OverviewNode` from `src/crack/core/nodes.py`, wired in `build_flow()` in `src/crack/analyses/backend/__init__.py`):

```text
BuildBundle -> Pipeline -> LayerCode -> Trace -> OverviewNode
```

- Analyzes the repository structure and maps files to six semantic layers: route, middleware, handler, service, database, response.
- `src/crack/analyses/backend/backend_crawl.py` walks the repo through `crack.core.list_files`, so it gets the repo containment and credential-name skips at walk time, symlink target names included (coderay-q2r.54). A source file over `DEFAULT_MAX_FILE_BYTES` is dropped from the walk, so it leaves the layer counts too; one that does not decode as UTF-8 is counted but its body is left out, and when that leaves every counted file out, `BuildBundle` aborts with the counts it has rather than claiming no backend was found (coderay-q2r.57). Nothing arrives cut off part way. Its `SKIP_DIRS` is `DEFAULT_SKIP_DIR` plus the backend extras, and `_spec.` marks a test (coderay-q2r.59). Bundle files are chosen round-robin across the layers, so one large spine file cannot starve the sampled ones, and are emitted grouped by layer (coderay-q2r.58). All four are deliberate divergences from the port source.
- Renders three views: the pipeline with file counts per layer, code snippets at layer boundaries, and a request trace through all six.

**Architecture** (five sequential nodes: four in `src/crack/analyses/architecture/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/architecture/__init__.py`):

```text
BuildBundle -> Inventory -> TechStack -> TraceRequest -> OverviewNode
```

- `src/crack/analyses/architecture/arch_crawl.py` overlays four sources into one bundle: process declarations (compose, k8s, `Procfile`, platform config), env var names from `.env` files, with credential values redacted out of every other source by `_redact` (coderay-q2r.14, a deliberate divergence from the port source, as is `_read` refusing a symlink whose target is credential-named, coderay-q2r.56), the union of `package.json` dependencies, and Terraform, plus SDK import lines from `git grep` as proof a connection is live.
- Inventory runs first among the LLM passes, and its numbered node list is reused by TechStack and TraceRequest, so all three name the same graph.
- Renders three views: every node banded run/rent/call/client, the technology behind each label, and one request traced hop by hop.

**Interfaces** (five sequential nodes: four in `src/crack/analyses/interfaces/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/interfaces/__init__.py`):

```text
FindRoutes -> ApiMenu -> TraceActions -> EndpointSequence -> OverviewNode
```

- `src/crack/analyses/interfaces/routes_find.py` finds entry-point files by framework convention and concatenates them, aggregators first. `read_files` resolves LLM-picked source paths and refuses any that leave the repo (`_within`, coderay-q2r.16), and both it and the crawl's `_read` go through `crack.core.readable`, which also refuses a credential-named target, whether the model named `.env` outright or a symlink inside the repo resolves to one (coderay-q2r.56; both are deliberate divergences from the port source).
- The only analysis using the engine's `when_empty="omit"` (the tour) and a Section's own `prefix`/`cards` hooks (the sequence diagram and its card). Four sections, like schema.
- EndpointSequence makes two LLM calls: one picks the endpoint and its source files, one draws the diagram from them. When neither the pick nor the fallback yields readable source it records `sequence_grounded=False`, and the card carries a warning instead of passing for a grounded diagram (coderay-q2r.25). The pick goes through `crack.core.yaml_call` (coderay-q2r.18, a divergence from the port source, like q2r.16, q2r.17 and q2r.56), so a malformed or empty reply retries with a varied tail instead of dropping straight to the fallback, and a transport error reaches the node's own `max_retries` instead of being swallowed.

**Schema** (six sequential nodes: five in `src/crack/analyses/schema/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/schema/__init__.py`):

```text
FindSchema -> SchemaTour -> TraceFlows -> TableDeepDive -> MigrationActs -> OverviewNode
```

- `src/crack/analyses/schema/schema_find.py` locates the schema by convention (Prisma, Rails, raw SQL, or concatenated `models.py`) and reads the migration directory with the most timestamped entries. Its `_read` goes through `crack.core.readable`, so a schema or migration that is a symlink to an in-repo credential file is refused by its target name (coderay-q2r.56, a deliberate divergence from the port source).
- SchemaTour runs first among the LLM passes: its ER diagram names the core tables the flows and deep-dive passes then reuse, filtered against the table names actually declared in the schema so an invented entity never reaches them.
- The only card-family analysis with a flag of its own (`--schema`; tour has `--instructions` and `--dry-run`), the only one that retitles the page from LLM output (`THEME.page_name`), and the only one using `when_empty="skip-note"`. TableDeepDive batches four tables per call, which is why its `ENV_DEFAULTS` is empty where the other card analyses raise `LLM_MAX_OUTPUT_TOKENS`.

**Git history** (five sequential nodes: four in `src/crack/analyses/git_history/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/git_history/__init__.py`):

```text
FetchHistory -> NameEras -> ProfileEras -> Graveyard -> OverviewNode
```

- The first of the two bespoke-renderer analyses (product-intent is the other): it declares its own `render_html`/`render_markdown` and `crack/core/render.py` defers to them, so it has no `SECTIONS` or `THEME`. `scripts/regen_golden.py` still reaches it through that delegation, but the bespoke divergence sets are per-analysis (`BESPOKE_DIVERGENCES`, keyed by name) because their mermaid line does not carry the card engine's `flowchart` option and they load different scripts.
- `src/crack/analyses/git_history/gitlog.py` is the only module that reads commit history from `git` (the architecture crawler shells out to `git grep` for SDK imports). Its seams: `redact_secret_files` strips credential-bearing file bodies from every diff before it reaches a prompt, keeping the path and the `--stat` entry, and recognises every header form `git show` emits, quoted paths and merge `diff --cc` included (coderay-q2r.34, q2r.36); the log record separator is NUL, which git refuses in a message, every record head is validated whole before parsing, and `show_diff` peels its argument to a commit behind `--end-of-options`, because the old 0x1e separator was legal inside a subject and let a hostile commit forge a record whose hash was `--output=<path>` (an arbitrary file write) or a raw blob (q2r.35); `repo_root` refuses a subdirectory, since `git -C` walks up to the enclosing repo, and `FetchHistory` warns on a shallow clone (q2r.38).
- `NameEras` and `ProfileEras` parse JSON through `crack.core.json_call`; `Graveyard` calls `call_llm` directly because its output is prose.

**Product intent** (five sequential nodes in `src/crack/analyses/product_intent/nodes.py`, wired in `build_flow()` in `src/crack/analyses/product_intent/__init__.py`; no `OverviewNode`):

```text
FetchRepo -> PainScene -> VariantSentence -> CompetitivePositioning -> SurprisesAndAbsences
```

- The second bespoke-renderer analysis; like tour, it has no shared overview. It renders four independent extractions (the pain scene, the one-sentence variant, a competitive positioning table with a mermaid diagram, and the surprises-and-absences lists) with its own `render_html`/`render_markdown`.
- `FetchRepo` reads the repo through `bundle()`, which keeps whole files in `list_files` order until a 650k-char budget is spent and reports how many it dropped (coderay-q2r.47; the port source concatenated everything with no cap). `--include`/`--exclude` are `.gitignore`-style patterns passed to `list_files`. An empty bundle stops the run before any LLM call.
- Ported text-only: the port source's `IllustratePain` node (a Gemini image of the pain scene written beside the report) is not included, so shared core carries no image provider and `init_shared` needs no `out_dir`. `CompetitivePositioning.normalize` also requires every competitor to carry a `name` (coderay-q2r.48).

Full architecture rationale and past review findings: `.full-review/*.md` (a comprehensive code review that produced the fixes now on `main`).

## Conventions & Patterns

- Card-family analyses (`backend`, `architecture`, `interfaces` and `schema`) declare `SECTIONS` and `THEME` and are rendered by `crack/core/render.py`. An analysis whose page shape does not fit declares its own `render_html` and `render_markdown` instead, and `crack/core/render.py` steps aside for it. Tour uses neither path: it predates the contract and writes its own multi-file output directly from `run()`, via `write_index_md`, `write_index_html` and `write_chapter_files`.
- Untrusted input (the target repo's own files, and anything the LLM echoes back from them) must be escaped before it reaches HTML/Mermaid output. This bit the project once (a confirmed stored-XSS bug); see `.full-review/02a-security.md` before touching rendering code.
- LLM structured output goes through `crack.core.yaml_call` or `crack.core.json_call`, not a bespoke `parse_yaml`/`parse_json`/`.format()` combo in pipeline nodes -- that duplication was a real bug (a cache/retry defect) fixed in a prior epic. Reuse those and `crack.core.fill()` for new LLM-calling code. Both share one `_REPLY_ERRORS` tuple that includes `TypeError`/`AttributeError`, because `normalize()` is handed whatever the model returned and a wrong-shaped reply used to escape every retry (coderay-q2r.33).
- Any file-content budget (`preview_budget`, `codebase_budget`) must be enforced by capping _how many files_ are included, not by raising a per-file floor -- that inversion was the root cause of two Critical scalability bugs.
- Tests live in `tests/`, run via plain `pytest`, no network/API key required -- LLM calls are faked at the `call_llm`/`yaml_call` boundary, not mocked deeper in the call stack.
