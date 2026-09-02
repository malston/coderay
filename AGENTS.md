# Agent Instructions

Crack runs three PocketFlow analyses: a multi-chapter tour, a server-side backend flow analysis, a multi-service architecture map, and an API surface guide. See `CLAUDE.md` for build/test commands, architecture, and project conventions -- read it before making changes.

This project uses **bd** (beads) for issue tracking; see the managed Beads sections below for commands and workflow. Run `bd prime` for full workflow context.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**

```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**

- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

## Architecture Overview

Crack dispatches to four analyses, each a PocketFlow pipeline:

**Tour** (five sequential nodes, `src/crack/analyses/tour/nodes.py`, wired in `src/crack/analyses/tour/flow.py`):

```text
SmartCrawl -> ExtractGraph -> Analyze -> Relate -> WriteChapters
```

- **SmartCrawl** walks the target repo (`src/crack/core/crawl.py`), builds a preview manifest, and asks the LLM which ~0.1-2% of files matter. Enforces `preview_budget` and `codebase_budget` so large repos can't blow the LLM's context window.
- **Analyze** / **Relate** / **WriteChapters** call the LLM via `crack.core.call_llm` and parse its YAML output via `crack.core.yaml_call`, which retries with a varied prompt on bad output (the retry-safe path -- don't reintroduce a local prompt-parsing loop that bypasses it).
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

- `src/crack/analyses/architecture/arch_crawl.py` overlays four sources into one bundle: process declarations (compose, k8s, `Procfile`, platform config), env var names from `.env` files, with credential values redacted out of every other source by `_redact` (coderay-q2r.14, the one deliberate divergence from the port source in that module), the union of `package.json` dependencies, and Terraform, plus SDK import lines from `git grep` as proof a connection is live.
- Inventory runs first and its numbered node list is reused by TechStack and TraceRequest, so all three passes name the same graph.
- Renders three views: every node banded run/rent/call/client, the technology behind each label, and one request traced hop by hop.

**Interfaces** (five sequential nodes: four in `src/crack/analyses/interfaces/nodes.py` plus the shared `OverviewNode`, wired in `build_flow()` in `src/crack/analyses/interfaces/__init__.py`):

```text
FindRoutes -> ApiMenu -> TraceActions -> EndpointSequence -> OverviewNode
```

- `src/crack/analyses/interfaces/routes_find.py` finds entry-point files by framework convention and concatenates them, aggregators first. `read_files` resolves LLM-picked source paths and refuses any that leave the repo (`_within`, coderay-q2r.16, the one deliberate divergence in that module).
- The only four-section analysis, and the only one using the engine's `when_empty="omit"` (the tour) and a Section's own `prefix`/`cards` hooks (the sequence diagram and its card).
- EndpointSequence makes two LLM calls: one picks the endpoint and its source files, one draws the diagram from them. The pick goes through `crack.core.yaml_call` (coderay-q2r.18, the second divergence in this analysis), so a malformed or empty reply retries with a varied tail instead of dropping straight to the fallback, and a transport error reaches the node's own `max_retries` instead of being swallowed.

## Conventions & Patterns

- Card-family analyses (today `backend`, `architecture` and `interfaces`; schema follows) declare `SECTIONS` and `THEME` and are rendered by `crack/core/render.py`. An analysis whose page shape does not fit declares its own `render_html` and `render_markdown` instead, and `crack/core/render.py` steps aside for it. Tour uses neither path: it predates the contract and writes its own multi-file output directly from `run()`, via `write_index_md`, `write_index_html` and `write_chapter_files`.
- Untrusted input (the target repo's own files, and anything the LLM echoes back from them) must be escaped before it reaches HTML/Mermaid output.
- LLM YAML parsing goes through `crack.core.yaml_call`, not a bespoke `parse_yaml`/`.format()` combo in pipeline nodes -- that duplication was a real bug fixed in a prior epic. Reuse `crack.core.yaml_call` and `crack.core.fill()` for new LLM-calling code.
- Any file-content budget (`preview_budget`, `codebase_budget`) must be enforced by capping _how many files_ are included, not by raising a per-file floor -- that inversion was the root cause of two Critical scalability bugs.
- Tests live in `tests/`, run via plain `pytest`, no network/API key required -- LLM calls are faked at the `call_llm`/`yaml_call` boundary, not mocked deeper in the call stack.

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

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->

## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
