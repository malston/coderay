# What a prompt receives

This document explains what crawl sends to a large language model (LLM), where
every character of it comes from, and how many times each prompt is sent in one
run. Read it before you edit a prompt template, add an analysis, or change
anything that sizes or budgets prompt text.

It assumes you have never worked on this codebase.

## The short version

Crawl reads a target repository, builds text out of what it finds, drops that
text into prompt templates, and sends the result to an LLM. Each of the seven
analyses does this three to five times. The templates are plain Markdown files
on disk with `{slot}` placeholders in them.

Nothing here is dynamic in a clever way. A prompt is a template file with its
slots replaced by strings.

## Vocabulary

You need these ten terms to read the tables below.

**Analysis.** One of the seven things crawl can produce from a repository:
`tour`, `backend`, `architecture`, `interfaces`, `schema`, `git-history`, and
`product-intent`. Each lives in `src/crawl/analyses/<name>/`. Each is a separate
pipeline with its own prompts, and they share very little.

**Node.** One step in an analysis. Crawl uses PocketFlow, a small pipeline
library, so every node has three methods that run in order: `prep(shared)` builds
the input, `exec(prep_res)` does the work, and `post(shared, prep_res, exec_res)`
stores the result. A node that talks to an LLM builds its prompt in `prep` and
sends it in `exec`. Six of the seven analyses wire their nodes in a
`build_flow()`; tour predates that and wires its own in
`src/crawl/analyses/tour/flow.py`.

**Shared.** One dictionary passed through every node in a run. A node reads what
earlier nodes wrote and writes what later nodes will read. When this document
says a slot is filled by an earlier LLM call, it means the value came off
`shared`.

**Crawl step.** The first node of every analysis. It walks the target repository
and produces text without calling an LLM. Each analysis crawls differently:
`schema` finds one schema file, `backend` samples files per layer,
`product-intent` concatenates whole files until a budget runs out, and
`git-history` reads commits instead of files.

**Bundle.** The text a crawl step assembled. For most analyses this is source
code joined together. The length of it is reported as `assembled_chars` (see
below).

**Template.** A Markdown file under `src/crawl/analyses/<name>/prompts/`. It
holds the task description, the output format the model must follow, and
`{slot}` placeholders. Templates are read by `read_prompt` and filled by `fill`,
both in `src/crawl/core/llm.py`. `fill` does literal string replacement rather
than `str.format`, so the JSON and Mermaid examples inside a template, which
contain their own braces, survive untouched.

**Slot.** A `{name}` placeholder in a template. Three kinds exist, and the
difference matters for every question in this document:

* *Crawled* slots carry text the crawl step built from the target repository.
  Their size scales with the repository.
* *Model* slots carry the output of an earlier LLM call in the same run. Their
  size cannot be known before the run happens.
* *Small* slots carry a number or a short label, such as a chapter index.

**House style.** One shared block of writing rules at
`src/crawl/core/prompts/house-style.md`, plus the evidence rules beside it at
`evidence-discipline.md`. Together they are 2,755 characters. A template that
asks the model for prose carries a `{house_style}` slot, and `read_prompt` fills
it before the node ever sees the template. A template whose reply gets parsed as
JSON or YAML carries no such slot and writes its own instructions. Nine of the
twenty-four templates are in that second group. `tests/test_prompts.py` pins
which is which, so adding a slot to the wrong template fails the suite.

**Preview.** A dictionary each analysis returns from its `preview(args)`
function. It runs the crawl step and nothing else: no LLM call, no network. It
reports counts, the file lists behind those counts, and up to three fixed keys:
`included`, `dropped`, and `assembled_chars`. `assembled_chars` is the length of
the text the crawl step built. A key is absent, never zero, where a crawler
computes no such quantity. Six of the seven analyses report all three;
`git-history` reports none of them, for the reason given in its section below.
The command `crawl estimate-token-usage <analysis> <repo>` prints it.

**Budget.** A character cap on how much repository text reaches the prompts.
`--codebase-budget` defaults to 650,000 characters and every analysis accepts
it. Budgets are enforced by including fewer files, not by shortening each file.

## How a prompt gets built

Four things end up in the string that goes over the wire:

1. The template's own text, which is fixed per template.
2. The house style block, for the fifteen templates that carry the slot.
3. Crawled text from the target repository.
4. Model slots filled by earlier calls in the same run.

Here is the schema analysis's second prompt, start to finish. `TraceFlows.prep`
in `src/crawl/analyses/schema/nodes.py` reads:

```python
def prep(self, shared):
    return fill(load_prompt("trace-flows.md"),
                schema=shared["schema"],
                table_list=", ".join(f"`{t}`" for t in shared["table_list"]))
```

`load_prompt` calls `read_prompt`, which reads `prompts/trace-flows.md` off disk
and replaces `{house_style}` with the shared block. Then `fill` replaces
`{schema}` with the schema text the crawl step read, and `{table_list}` with the
table names the previous LLM call named. The result is one string. `exec` sends
it.

## Reading the tables

Each analysis below gets one row per template. The columns mean this:

**shell** -- the template's own characters after the slot placeholders are
subtracted, including the house style block where the template carries one. This
number does not change with the repository. It is the floor you pay per call.

**house** -- whether this template carries `{house_style}`. A template marked
"no" writes its own instructions, usually because its reply is parsed rather
than read.

**crawled** -- how many characters of repository text this prompt carries, for
the repository measured. This is the number that grows with a bigger target.

**per call** -- shell plus crawled, for one send. Model slots are excluded
because their size is not knowable before the run.

**fires** -- how many times this prompt is sent during one complete run. Some of
these are fixed, some depend on the repository, and some depend on what the
model answered earlier.

The numbers come from `~/code/uigen`, a small Next.js application with a Prisma
schema, at a 650,000-character budget. `git-history` alone is measured against
`~/code/coderay`, because uigen is not a git checkout. Measured
2026-09-12 against commit `100de1f`. The shell figures move whenever a template
is edited; reproduce them with the scripts named at the end.

## tour

Five nodes. Reads 62 source files on this repository. Builds a *manifest*, which
is the first 800 characters of each file, and asks the model which files matter.
The files the model picks become the bundle that the other three prompts carry.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `select-files.md` | 1,738 | no | 44,543 (manifest) | 46,281 | 1 |
| `identify-abstractions.md` | 1,465 | no | bundle | see note | 1 |
| `analyze-relationships.md` | 680 | no | bundle | see note | 1 |
| `write-chapter.md` | 3,288 | yes | bundle | see note | once per chapter |

Note: tour's `assembled_chars` is the manifest, which is 44,543 characters here.
It is not the bundle. The bundle is built in `SmartCrawl.post` out of the files
the model picked, and on this repository `target_files` resolves to 20 of the 62
found. No preview can know which 20. Sizing tour's last three prompts therefore
needs an estimate rather than a measurement. The existing estimator at
`src/crawl/analyses/tour/render.py:336` reads files up to the budget and returns
547,578 characters for this repository, which is close to every readable file.
Whether that is a fair stand-in for 20 files is an open question, tracked as
`coderay-3le`.

The chapter count is the model's answer from `identify-abstractions.md`, whose
prompt asks for 5 to 10. `DRY_RUN_CHAPTER_GUESS` in `render.py` takes the
midpoint of that range, 8, as its stand-in.

`write-chapter.md` is the only template in the codebase carrying a cache
breakpoint. Everything before the marker is the stable prefix the provider
caches across the chapter calls, so repeated chapters cost less than the raw
character count suggests.

## backend

Five nodes. Maps files to six layers (route, middleware, handler, service,
database, response) and samples them into one bundle of 5,988 characters here.
All three prompts carry the same bundle.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `pipeline.md` | 5,501 | yes | 5,988 | 11,489 | 1 |
| `layer-code.md` | 4,931 | yes | 5,988 | 10,919 | 1 |
| `trace.md` | 5,605 | yes | 5,988 | 11,593 | 1 |
| shared overview | 3,351 | voice only | 0 | 3,351 | 1 |

## architecture

Five nodes. Overlays process declarations, environment variable names, declared
dependencies, and software development kit (SDK) import lines into one bundle of
1,575 characters here. The `inventory` prompt runs first, and its numbered node
list is reused by the two after it, so all three name the same graph.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `inventory.md` | 5,929 | yes | 1,575 | 7,504 | 1 |
| `tech-stack.md` | 5,291 | yes | 1,575 plus inventory | 6,866 plus | 1 |
| `trace-request.md` | 5,177 | yes | 1,575 plus inventory | 6,752 plus | 1 |
| shared overview | 3,351 | voice only | 0 | 3,351 | 1 |

## interfaces

Five nodes. Finds entry-point files by framework convention and concatenates
them into 2,837 characters here. `EndpointSequence` makes two calls: one picks
the endpoint and its source files, and one draws the diagram from them. The pick
uses `_PICK_PROMPT`, a string constant in `nodes.py` rather than a file on disk.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `api-menu.md` | 5,426 | yes | 2,837 | 8,263 | 1 |
| `trace-action.md` | 5,348 | yes | 2,837 | 8,185 | 1 |
| `_PICK_PROMPT` (inline) | 602 | no | 2,837 plus menu | 3,439 plus | 1 |
| `endpoint-sequence.md` | 6,155 | yes | 2,837 plus handler source | 8,992 plus | 1 |
| shared overview | 3,351 | voice only | 0 | 3,351 | 1 |

`endpoint-sequence.md` carries the route text as `{routes}`, truncated to 60,000
characters in this one prompt, plus `{handler_source}`, which holds whatever
files the pick named, read back off disk, or the fallback file when none of them
could be read. That second part cannot be sized before the run, the same way
tour's bundle cannot.

## schema

Six nodes. Finds one schema file by convention, 797 characters here, and the
migration directory with the most timestamped entries.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `schema-tour.md` | 5,581 | yes | 797 | 6,378 | 1 |
| `trace-flows.md` | 5,098 | yes | 797 | 5,895 | 1 |
| `table-deep-dive.md` | 4,629 | yes | 797 | 5,426 | once per 4 tables |
| `migration-acts.md` | 5,158 | yes | 104 (names) | 5,262 | 0 or 1 |
| shared overview | 3,351 | voice only | 0 | 3,351 | 1 |

Two things here catch out anyone estimating cost.

`table-deep-dive.md` fires once per batch of four tables, and the table count
comes from the first LLM call's entity relationship diagram. A schema with 30
core tables sends this prompt 8 times, each carrying the full schema text again.

`migration-acts.md` fires zero times below `MIGRATION_FLOOR`, which is 4. uigen
has 3 migrations, so on this repository that prompt is never built and never
paid for. It also carries the migration *names* rather than the schema, which is
why `assembled_chars` for this analysis covers the schema text alone.

## git-history

Five nodes. This is the analysis that reads commits rather than files, and the
one carrying no `assembled_chars` at all: its crawl step returns a commit
record, and the prompt text is assembled downstream in `NameEras.prep` and
`ProfileEras.prep`, with diffs fetched later still. Measured against
`~/code/coderay`: 347 commits, 9 bulk additions, and 3 bulk deletions.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `name-eras.md` | 3,827 | no | 4,352 (summaries) | 8,179 | 1 |
| `profile-era.md` | 3,417 | no | 47,982 at most | 51,399 | once per era |
| `graveyard-entry.md` | 6,031 | yes | 12,000 | 18,031 | once per grave, at most `max_graves` |
| shared overview | 3,351 | voice only | 0 | 3,351 | 1 |

`name-eras.md` carries four summaries built from the whole log: a commit
heatmap, a pivot summary, and one summary each for bulk additions and bulk
deletions, the last two carrying commit subject lines verbatim. Pure renames are
dropped before summarising, so this figure comes from calling `NameEras.prep`
rather than rebuilding its logic.

`profile-era.md` is the largest single prompt in the codebase. Each call carries
one era's commit stream, sampled down to `profile_max_commits`, which defaults
to 400, plus five landmark diffs, each capped at `profile_diff_chars`, which
defaults to 2,500. The 47,982 above is an upper bound: it sizes a single era
holding the entire 347-commit history, and a real era holds a slice of it. The
number of eras is the previous node's LLM answer, so neither the era count nor
any single era's true size can be known before the run.

`graveyard-entry.md` carries one diff with `--stat`, capped at 12,000
characters, and fires once per grave up to `max_graves`, which defaults to 6. A
repository with no bulk deletions buys nothing here.

## product-intent

Five nodes. Concatenates whole files in `list_files` order until the budget runs
out. On uigen that kept all 62 files and dropped none, assembling 557,285
characters. All four prompts carry that same bundle, and none of them carries
the house style block.

| template | shell | house | crawled | per call | fires |
|---|---|---|---|---|---|
| `pain-scene.md` | 1,571 | no | 557,285 | 558,856 | 1 |
| `variant-sentence.md` | 1,856 | no | 557,285 | 559,141 | 1 |
| `competitive-positioning.md` | 4,628 | no | 557,285 | 561,913 | 1 |
| `surprises-and-absences.md` | 3,246 | no | 557,285 | 560,531 | 1 |

This analysis has no shared overview node.

uigen is small enough to fit the budget whole. A larger target shows what the
budget does: the same crawl against `~/code/coderay` keeps 133 files, drops 309,
and assembles 649,913 characters against the 650,000 cap. This crawler is also
the only one that counts files it could not decode, reported separately from the
ones a budget dropped.

## Five things to know before you estimate cost

The crawled text is sent more than once. Product-intent sends its whole
bundle four times. Backend sends its bundle three times. Schema sends the schema
text twice plus once per deep-dive batch. Total input for a run is the bundle
size times the number of prompts that carry it.

The house style block is not on every prompt. Nine of twenty-four templates
are own-voice: all four of product-intent's, three of tour's, and two of
git-history's. Adding a flat 2,755 characters per call overstates those nine.

On a small repository the template dominates. The schema analysis on uigen
sends 797 characters of actual schema inside a 5,581-character prompt. The ratio
inverts completely on a large repository, which is why a per-call estimate
has to keep the two parts separate.

Some prompts fire zero times. `migration-acts.md` below the floor, and the
whole graveyard pass on a repository with no bulk deletions. Assuming every node
fires overquotes the run.

Three call counts are not knowable before the run. Schema's batch count
needs the table list from the first call. Git-history's era count and grave
count both come from `NameEras`. Tour's chapter count comes from
`identify-abstractions`. Any estimate reports these as a range or says the
number is unknown until the run happens.

## The shared overview node

Five of the seven analyses end with `OverviewNode`, in `src/crawl/core/nodes.py`.
It writes the page's welcome text and a short introduction per section. Its
prompt is a string constant in `src/crawl/core/overview.py`, not a file under a
`prompts/` directory: an 1,148-character shell plus the house style block with
the evidence rules left out, which is 2,203 characters. That fixed 3,351 is the
figure in the tables above. On top of it each analysis adds its own section
titles, gists, and a one-line facts string, a few hundred characters in total.

It carries no repository text at all, so it costs the same on a large repository
as on a small one. Tour and product-intent do not use it; both write their own
page layout.

## Reproducing these numbers

`scripts/prompt_anatomy.py` measures every template under a `prompts/`
directory. It runs each analysis's crawl step and nothing else: no LLM call, no
network. Two prompts are string constants in Python rather than files, so the
script does not cover them: `_PICK_PROMPT` in `interfaces/nodes.py` and the
overview prompt in `core/overview.py`. Both are measured by hand above.

```bash
uv run python scripts/prompt_anatomy.py <repo_path>                  # all seven
uv run python scripts/prompt_anatomy.py <repo_path> schema backend   # named ones
uv run python scripts/prompt_anatomy.py <repo_path> schema --dump trace-flows
```

`--dump` prints one prompt with its slots filled, which is the fastest way to
see what a template really looks like once it is built. `--codebase-budget`
takes the same value as the command-line flag of the same name, so you can see
what a budget change does to the text a run sends.

The script holds one table recording where each slot's value comes from, which
is not derivable from a slot name. That table is checked against the templates on
every run. A renamed, added, or removed slot stops the script with a message
naming the template, rather than quietly reporting a wrong number.

Run it through `uv run`, not a bare `python`. A bare interpreter can resolve the
editable `crawl` package to a different checkout. Check with
`uv run python -c "import crawl; print(crawl.__file__)"`.

For the crawl counts alone, without any of the prompt sizing, the shipped
command is:

```bash
uv run python -m crawl.cli estimate-token-usage <analysis> <repo_path>
```

## Where to look next

* `src/crawl/core/llm.py` -- `read_prompt` and `fill`, twenty lines that explain
  most of this document.
* `src/crawl/core/preview.py` -- the `Preview` shape and what each key promises.
* `tests/test_prompts.py` -- the rules a template has to satisfy, including
  which templates may carry the house style slot.
* `CLAUDE.md` -- the full conventions list, including why LLM output goes
  through `yaml_call` and `json_call` rather than a local parse.
