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

Crack dispatches to three analyses, each a PocketFlow pipeline:

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
- Renders three views: the pipeline with file counts per layer, code snippets at layer boundaries, and a request trace through all six.

**Architecture** (five sequential nodes: four in `src/crack/analyses/architecture/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/architecture/__init__.py`):

```text
BuildBundle -> Inventory -> TechStack -> TraceRequest -> OverviewNode
```

- `src/crack/analyses/architecture/arch_crawl.py` overlays four sources into one bundle: process declarations (compose, k8s, `Procfile`, platform config), env var names from `.env` files (every other source is sent whole, values included -- see coderay-q2r.14), the union of `package.json` dependencies, and Terraform, plus SDK import lines from `git grep` as proof a connection is live.
- Inventory runs first and its numbered node list is reused by TechStack and TraceRequest, so all three passes name the same graph.
- Renders three views: every node banded run/rent/call/client, the technology behind each label, and one request traced hop by hop.

Full architecture rationale and past review findings: `.full-review/*.md` (a comprehensive code review that produced the fixes now on `main`).

## Conventions & Patterns

- Card-family analyses (today `backend` and `architecture`; interfaces and schema follow) declare `SECTIONS` and `THEME` and are rendered by `crack/core/render.py`. An analysis whose page shape does not fit declares its own `render_html` and `render_markdown` instead, and `crack/core/render.py` steps aside for it. Tour uses neither path: it predates the contract and writes its own multi-file output directly from `run()`, via `write_index_md`, `write_index_html` and `write_chapter_files`.
- Untrusted input (the target repo's own files, and anything the LLM echoes back from them) must be escaped before it reaches HTML/Mermaid output. This bit the project once (a confirmed stored-XSS bug); see `.full-review/02a-security.md` before touching rendering code.
- LLM YAML parsing goes through `crack.core.yaml_call`, not a bespoke `parse_yaml`/`.format()` combo in pipeline nodes -- that duplication was a real bug (a cache/retry defect) fixed in a prior epic. Reuse `crack.core.yaml_call` and `crack.core.fill()` for new LLM-calling code.
- Any file-content budget (`preview_budget`, `codebase_budget`) must be enforced by capping _how many files_ are included, not by raising a per-file floor -- that inversion was the root cause of two Critical scalability bugs.
- Tests live in `tests/`, run via plain `pytest`, no network/API key required -- LLM calls are faked at the `call_llm`/`yaml_call` boundary, not mocked deeper in the call stack.
