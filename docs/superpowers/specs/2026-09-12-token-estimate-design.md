# Estimating a run's tokens and cost before it happens (coderay-05w.2)

## Problem

`crawl estimate-token-usage <analysis> <repo>` runs an analysis's crawl step and
prints what it found. It ends with a line saying it does not estimate tokens or
cost. Only `tour` estimates cost, through its own `--dry-run` flag and
`estimate_dry_run_cost` in `analyses/tour/render.py`.

A user deciding whether to run `product-intent` against a large monorepo has no
way to find out what it will cost short of running it.

The bead warns against forcing one formula across seven analyses, because the
node graphs differ: schema batches tables four at a time, git-history's era
count is only known after the log fetch, and interfaces branches on whether the
endpoint pick worked.

## What the measurement showed

`docs/prompt-anatomy.md` measured all 24 templates against real repositories.
The shape is more uniform than the bead assumed. Every prompt in every analysis
is the same three quantities:

* a **shell**, fixed per template, which includes the house style block for the
  15 templates carrying the slot
* a **body**, the repository text it carries, which for six of seven analyses is
  `assembled_chars` from the `Preview` multiplied by how many crawled slots the
  template has
* a **call count**, how many times it is sent

What actually differs between analyses is not the formula. It is where the body
size comes from, and whether the call count is known.

### Where each body size comes from

| analysis | body |
|---|---|
| backend, architecture, schema, product-intent | `assembled_chars` from the `Preview` |
| interfaces | `assembled_chars`, truncated to 60,000 in `endpoint-sequence.md`, plus `handler_source` which is model-picked |
| git-history | fixed caps the nodes pass to `show_diff`: 2,500 per era diff, 12,000 per grave diff, plus a commit stream sampled to `profile_max_commits` |
| tour | the LLM-picked bundle, which no preview can size. See `coderay-3le`. |

### Every unknowable call count has a bound in the code

This is the finding that makes a useful estimate possible. Each count the model
decides is bounded by the prompt that asks for it, or by a flag:

| count | bound | where it is stated |
|---|---|---|
| tour chapters | 5 to 10 | `identify-abstractions.md` asks for "5 to 10 most important core abstractions" |
| git-history eras | 3 to 5 | `name-eras.md` asks for "a series of 3-5 named ERAS" |
| git-history graves | 0 to `max_graves`, default 6 | `Graveyard.prep` |
| schema deep-dive batches | about 5 | `schema-tour.md` asks for "about 20 tables"; `TableDeepDive.BATCH` is 4 |
| schema migration acts | 0 or 1 | `MIGRATION_FLOOR` against the migration count the preview already has |

None of these is a guess. Each is read from a file in the repository, which
means a prompt edit that changes a range shows up as a failing test rather than
a stale number.

## Design

### One contract, in `crawl/core/estimate.py`

Each analysis declares a prompt plan beside its existing `preview(args)`:

```python
def prompt_plan(args, preview) -> list[Prompt]
```

It takes the `Preview` the command already computed, so the repository is
crawled once rather than twice. That is what `assembled_chars` was added for
(coderay-05w.5).

```python
@dataclass(frozen=True)
class Prompt:
    template: str          # the file or constant, for the per-prompt breakdown
    shell_chars: int       # fixed cost, house style included
    body_chars: int        # repository text this prompt carries, per call
    calls: tuple[int, int] # (low, high); equal when the count is fixed
    note: str = ""         # what a range assumes, or what the body leaves out
```

Core then does the token math once, for every analysis:

```python
def estimate(plans, provider, model, max_output_tokens) -> Estimate
```

### Why a range rather than a single number

`calls` is a `(low, high)` pair rather than an int. A fixed count sets both to
the same value. The alternative, an optional int that is `None` when unknown,
forces the reader to add up an unknown number of calls themselves, and forces
the formatter to print a total it cannot compute.

The range costs one tuple and buys a printable answer for all seven analyses.

### Output-token cap comes from the analysis, not the ambient environment

`max_output_tokens()` reads `LLM_MAX_OUTPUT_TOKENS` off the environment. Four
analyses raise it to 32768 through their own `ENV_DEFAULTS`; schema,
git-history, and product-intent leave it at the default. So the estimate must
read the cap inside `env_defaults(analysis.ENV_DEFAULTS)`, the same context
manager `runner.run_analysis` wraps the real flow in.

Reading it outside that context reports the wrong worst case for four of the
seven. `tests/test_tour.py:15` already pins this behaviour for tour, and the
port of that test is the guard for the rest.

### What each analysis's prompt_plan looks like

Six are a few lines: read the template, subtract the slots, multiply
`assembled_chars` by the crawled-slot count, and set `calls`.

Three need their own handling, and each gets it in its own module rather than in
a branch inside core:

* **schema** computes its batch range from the table bound and `BATCH`, and
  returns `calls=(0, 1)` for `migration-acts.md` by checking the migration count
  against `MIGRATION_FLOOR`. The preview already carries that count, so this
  needs no second crawl.
* **git-history** sizes from the caps its nodes pass to `show_diff` rather than
  from `assembled_chars`, which it does not report. `name-eras.md` is sized by
  calling `NameEras.prep`, the way `scripts/prompt_anatomy.py` does and the way
  tour's preview reuses `SmartCrawl.prep`.
* **tour** keeps its existing `_codebase_preview_text` approach, with the
  assumption stated in the output and `coderay-3le` open against it. Changing
  the heuristic is that bead's job, not this one's.

### What the estimate cannot know, it says

Two bodies are genuinely unsized: tour's bundle and interfaces'
`handler_source`. Both get a `note` naming what is left out, printed beside the
number rather than folded into it. This follows the rule 05w.4 set: absent and
named, never silently zero.

### Removing tour's --dry-run

`tour --dry-run` becomes `estimate-token-usage tour`. That touches:

* `analyses/tour/__init__.py`: the flag, the `args.dry_run` branch, and the
  `estimate_dry_run_cost` and `format_dry_run_summary` imports
* `cli.py:15-17`: `NOT_PREVIEWABLE` and the comment above it, since `--dry-run`
  stops being a flag the preview refuses and becomes one that does not exist
* `tests/test_estimate_token_usage.py:547`: its premise changes for the same
  reason
* every fake-args namespace passing `dry_run=False`, in `tests/test_tour.py` and
  `tests/test_write_chapters.py:82`

The dry-run tests at `tests/test_tour.py:193-250` and `tests/test_main.py:313`
are ported to the new command, not deleted.

## Acceptance

* Every analysis reports an input-token estimate and a worst-case output-token
  estimate, the latter computed inside its own `ENV_DEFAULTS`
* Cost is reported as a low and high dollar figure when the resolved model is
  priced, and "unknown" when it is not
* A call count the model decides is reported as a range whose bound is read from
  the prompt or flag that sets it, with a test pinning the range to that source
* A body the estimate cannot size is named in a note rather than counted as zero
* `crawl tour ./repo --dry-run` fails with "unrecognized arguments"
* The existing tour dry-run tests pass against the new command

## Open question for Mark

The ranges above are read from prompt text such as "5 to 10". A prompt edit
changes the range. Two ways to keep them honest:

1. Parse the bound out of the prompt file at estimate time. Always current, and
   brittle against a rewording.
2. Hold the bound as a constant beside the analysis, with a test asserting the
   prompt still says what the constant claims. A reworded prompt fails the test
   with the constant named.

Option 2 is the recommendation. It matches how `scripts/prompt_anatomy.py`
guards its slot table, and it fails loudly rather than silently reading a
number out of prose.
