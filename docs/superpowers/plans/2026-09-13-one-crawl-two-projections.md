# One crawl, two projections (coderay-5fp)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to work this task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `crawl estimate-token-usage <analysis> <repo>` reads the repository once. Today two of the seven analyses read it twice.

**Decision:** `coderay-lfd` records why this shape was chosen over memoizing the fetch or widening `Preview` again. Read it before changing the approach.

**Bead:** `coderay-5fp`

## The shape

Each analysis grows one function and keeps its two existing ones, now as
projections of it:

```python
def crawl(args)                      # whatever this analysis's crawl produces
def preview(args, crawled=None)      # -> Preview, for the reader
def prompt_plan(args, crawled)       # -> list[Prompt], for the estimate
```

The crawl result is private to its analysis. Nothing outside it reads the
shape, so there is no shared type to negotiate across seven different ones.

`crawled` is optional on `preview` and required on `prompt_plan`. That is
deliberate and it is the whole reason this plan is small: 77 call sites pass
`preview(args)` today and none of them care where the crawl came from, so
churning them buys nothing. `prompt_plan` has 22 call sites and its second
argument changes meaning, from the `Preview` to the crawl result, so those do
have to move.

The CLI is the one caller that benefits, and it says so plainly:

```python
crawled = analysis.crawl(args)
print(format_preview(analysis.NAME, args.repo_path, analysis.preview(args, crawled)))
if not aborted(result):
    plan = analysis.prompt_plan(args, crawled)
```

## What each analysis's crawl returns

Already one or two statements at the top of each `preview`, which is why this
is mechanical rather than a restructuring.

| analysis | the crawl today | returns |
|---|---|---|
| `tour` | `SmartCrawl().prep(shared)` after `init_shared` | the `shared` dict |
| `backend` | `build_bundle(repo, max_chars=budget)` | `(bundle, stats)` |
| `architecture` | `build_bundle(repo, max_chars=budget)` | `(bundle, stats)` |
| `interfaces` | `crawl_routes(repo, max_chars=budget)` | `(routes, found, read)` |
| `schema` | `find_schema(...)` and `find_migrations(...)` | `(schema, mig_names)` |
| `git-history` | `repo_root(...)` then `FetchHistory().exec(...)` | the log record |
| `product-intent` | `bundle(repo, include, exclude, max_chars)` | `(codebase, stats)` |

Two carry a guard that must move with the crawl, not stay behind in `preview`:
`git-history`'s `repo_root` and `tour`'s `SystemExit` on no source files.

## Global constraints

- Every step is test-first. Watch the test fail, and know it failed for the
  reason you expected, before writing the code.
- `uv run pytest`, never a bare `pytest`. A bare interpreter can resolve the
  editable `crawl` package to a different checkout.
- After a step that restores a same-length token, `find src -name __pycache__
  -type d -exec rm -rf {} +`. Python invalidates bytecode by mtime and size.
- Run the suite under a clean environment, `CODEBASE_BUDGET=1`, and
  `LLM_MAX_OUTPUT_TOKENS=128000` before calling any step done.
- No behaviour change is intended anywhere. Every number the command prints
  before this work must be identical after it, and step 10 checks that against
  captured output rather than against memory.

## Tasks

### 1. Prove the duplicate read, so the fix has a witness

- [ ] Write a test that counts filesystem reads across one
      `preview` + `prompt_plan` pair, for `tour` and `git-history`. Patch
      `crawl.core.files.safe_read` and `gitlog.git_log_commits` with counting
      wrappers rather than asserting on wall-clock time, which is not stable
      in CI.
- [ ] Watch it fail: today the counts are roughly double.
- [ ] Leave it failing. Steps 2 through 8 turn it green, and it is the one
      test that says whether this work achieved anything.

### 2. `crawl(args)` on the five analyses whose preview already has it inline

`backend`, `architecture`, `interfaces`, `schema`, `product-intent`.

For each:

- [ ] Add `def crawl(args)` returning exactly what the preview's first
      statements compute.
- [ ] `preview(args, crawled=None)` starts `crawled = crawl(args) if crawled
      is None else crawled` and reads from it.
- [ ] `prompt_plan(args, crawled)` reads the crawl result instead of the
      `Preview`. `assembled_chars` becomes `len(bundle)` at the source.
- [ ] The existing tests for that analysis stay green with no edit. If one
      needs editing, the change was not behaviour-preserving; stop and find
      out why.

### 3. `crawl(args)` on `git-history`

- [ ] `crawl(args)` runs `repo_root(args.repo_path)` then
      `FetchHistory().exec(args.repo_path)` and returns the log. The guard
      moves with the crawl, because it is what makes the crawl legitimate.
- [ ] `prompt_plan` reads that log rather than re-running the fetch, and
      calls `NameEras().prep` once against it.
- [ ] Step 1's read count for `git-history` drops to one.

### 4. `crawl(args)` on `tour`

- [ ] `crawl(args)` builds `shared` via `init_shared` and runs
      `SmartCrawl().prep(shared)`, returning `shared`. The `SystemExit` on no
      source files is caught by `preview` as it is today, so the abort note is
      unchanged.
- [ ] `prompt_plan` reads `shared["previewed_files"]` rather than
      `preview["included"]`, which is the same list under a different name.
- [ ] `estimated_codebase_chars` still reads every previewed file, and that
      read stays. It is not a repeat of the preview's. What it keeps is each
      file's character count and whether the file decodes at all; reading is
      how it learns both, and it discards the text. The preview's
      `safe_read(path, max_chars=800)` calls `f.read(800)`, which stops early,
      so the preview never had a length to hand over.
- [ ] Do not swap it for `os.path.getsize`. Measured on 1,250 files from a
      real repository: the byte size differs from the character count for 761
      of them, worst gap 1,054 characters, and a `stat` cannot tell you a file
      fails to decode. PR #115 reports that unreadable count on purpose, so a
      figure resting on two readable files out of forty says so. The read it
      would replace costs 2.4 ms more than the preview's own read over the
      same files.
- [ ] Say both of those in a comment where the next reader meets the call.
      The first draft of this plan said the estimator "needs whole files",
      which reads like duplicated work and is the wrong thing to leave behind.

### 5. The CLI crawls once

- [ ] `cli.py` calls `analysis.crawl(args)` and passes the result to both
      projections.
- [ ] Keep the `redirect_stdout` wrapper around the crawl, since it is the
      crawl that prints progress.
- [ ] Step 1's test now passes for both analyses. If it does not, stop: the
      remaining read is the thing this plan exists to remove.

### 6. `scripts/prompt_anatomy.py` stops reaching behind the contract

- [ ] It sets `preview["_log"]` and `preview["_repo_path"]` to smuggle the
      git-history record. Both go: it calls `crawl(args)` like the CLI.
- [ ] `_git_history_chars` takes the log as an argument.
- [ ] The tables it prints are unchanged. Diff the output against a capture
      taken before the change.

### 7. Retire `assembled_chars`

- [ ] Confirm again that nothing but `prompt_plan` read it. `format_preview`
      does not, and `coderay-05w.3` will print `included` and `dropped`, not
      this. If a consumer has appeared since, stop and re-decide.
- [ ] Remove the key from `Preview`, from every `preview` that returns it, and
      from the tests in `tests/test_estimate_token_usage.py` that pin it.
- [ ] `included` and `dropped` stay. They are display data with a use coming.
- [ ] Update the `Preview` docstring, and the convention paragraphs in
      `CLAUDE.md` and `AGENTS.md` that describe the three keys, to describe
      two.

### 8. Move the 22 `prompt_plan` call sites

- [ ] Mechanical: the second argument becomes the crawl result.
- [ ] `tests/test_prompt_plan.py` holds 18 of them and has a `_args` helper
      already, so most become one line each.

### 9. Documentation

- [ ] `docs/prompt-anatomy.md` describes the `Preview` contract and the three
      canonical keys. Update it to two, and to the new three-function shape.
- [ ] Its "What consumes these numbers" section names
      `prompt_plan(args, preview)`. Correct the signature.

### 10. Verify nothing moved

- [ ] Before starting, capture `estimate-token-usage` output for all seven
      analyses against two real repositories, to a file.
- [ ] At the end, capture again and diff. Any difference is a bug in this
      work, not an improvement, unless step 7 removed a line deliberately.
- [ ] Full suite under the three environments named in the constraints.
- [ ] Step 1's read-count test green.

## What this plan does not do

It does not touch `run()`. A real run crawls inside its flow, through the same
node, and unifying that with these two projections is a larger change with no
user benefit: a run crawls once already.

It does not change any number the command prints. If a figure moves, something
is wrong.
