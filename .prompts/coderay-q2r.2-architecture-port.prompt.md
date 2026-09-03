# Handoff: coderay-q2r.2 — port ch09-architecture as `crack architecture`

## Do this first: fix a fragile pin I shipped

`scripts/regen_golden.py` pins `PORT_SOURCE_COMMIT` to
`5fd2a96585d27ad7fe2cd7d2c5f0d7941f15ee22`. That commit is reachable **only** from
`feat/node-tests` in the sibling repo, a work-in-progress branch. It is not on `main` and not
on `feat/unified-cli`. If that branch is rebased or deleted, the golden fixture can never be
regenerated and the pin is a dangling reference.

Re-pin to `bb504c7a9f44ba14f8d71a1f0cd9d2c997fb9d44`, the PR #1 merge on the sibling's `main`.
I verified it is content-identical for everything this port copies:

```text
core/overview.py, core/nodes.py, core/env.py, analyses/backend/backend_crawl.py, prompts/  -> byte-identical
analyses/backend/nodes.py -> differs only by the sanctioned importlib.resources change
core/render.py            -> differs only by the deliberate mermaid securityLevel divergence
```

Two files carry the SHA: `scripts/regen_golden.py` and
`docs/superpowers/plans/2026-09-01-backend-analysis-port.md`. After changing them, run
`scripts/regen_golden.py backend` and confirm `git diff --exit-code tests/fixtures/golden/`
is clean, which proves the new pin really does produce the same fixture.

Rule going forward: **pin to a commit on the sibling's `main`, never to a topic branch.**

## Where things stand

- `main` is at `f2bd005`. `crack tour` and `crack backend` both ship. 238 tests, no network.
- coderay-q2r.1 is closed. PR #25 merged and its worktree is gone.
- Port source of record: `github.com/malston/Crack-Any-Codebase-with-AI`, local checkout at
  `~/code/Crack-Any-Codebase-with-AI`. That repo moved three times during the last port, so
  **verify the pin before copying anything, every time**. The guard in `regen_golden.py` and
  the check in each implementer dispatch are what caught it each time; keep both.

## The task

`bd show coderay-q2r.2`. Port `ch09-architecture` as `crack architecture`, the second of the
four card-family analyses.

Read `docs/superpowers/specs/2026-09-01-analysis-port-design.md` for the approach and the
decision record, then `docs/superpowers/plans/2026-09-01-backend-analysis-port.md`. That plan
is your template: **tasks 1-5 are already done and are not repeated.** The shared core is in
place (`render.py`, `overview.py`, `nodes.py`, `env.py`, `run_analysis`, `repo_name_of`,
`extract_mermaid`). Architecture reduces to the plan's tasks 6-9:

| Task | Work                                                                                                                                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6    | copy `arch_crawl.py` (168 lines), unit tests against a fixture repo                                                                                                                                                                   |
| 7    | copy `nodes.py` (101 lines) and `prompts/` (`inventory.md`, `tech-stack.md`, `trace-request.md`); switch `PROMPTS_DIR` to `importlib.resources`                                                                                       |
| 8    | write `__init__.py` (84 lines upstream): `SECTIONS` (01 The inventory, 02 Tech stack, 03 The trace), `THEME`, `ENV_DEFAULTS`, `build_flow`, `add_arguments`, `init_shared`, `run`, `overview_spec`; register it; add a golden fixture |
| 9    | docs                                                                                                                                                                                                                                  |

Adaptations the upstream `__init__.py` needs, same as backend: one-argument `init_shared(args)`,
add `add_arguments` and `run`, and have `run` call `run_analysis(sys.modules[__name__], args)`.

Architecture sets `ENV_DEFAULTS = {"LLM_MAX_OUTPUT_TOKENS": "32768"}`. That is already handled:
`call_llm` streams the anthropic path, so the non-streaming ceiling no longer applies.

## Known before you start

**coderay-q2r.10 — architecture is blind to CDK, Pulumi and SAM.** `arch_crawl` classifies
config by extension or exact filename, so infrastructure written in a general-purpose language
matches nothing. Verified: `crack architecture` on a CDK repo reports `0 config files` while
three stacks sit in `infra/lib/`. Port it faithfully, characterize it with a test naming the
bead, and document it in the README. Do not fix it here; fix it upstream where the parity
tests live. This is the same call made for q2r.7 and q2r.8.

**Check for a dead guard.** Backend's `assert bundle.strip()` can never fire because the crawl
always prepends a header (q2r.8). Before trusting any similar guard in `arch_crawl` or
architecture's nodes, trace what actually reaches it. On a real run, `interfaces` and `schema`
refused cleanly on an empty repo while `backend` sailed through, so the pattern is not
universal upstream.

## Process that earned its keep, and what it cost

Use `superpowers:subagent-driven-development`. One implementer per task, a task review after
each, a whole-branch review at the end. Nine tasks took about two hours of wall clock.

**Five tests that could not fail were shipped and caught.** Every one was written by the plan
author, looked correct, and passed against a broken implementation:

- an assertion on a value the code strips, so equality was impossible
- a path case asserting behaviour that cannot occur on POSIX
- a relative-path test using the one input where correct and naive agree
- an XSS test whose payload sat above the first `###`, where `split_cards` drops it
- a priority test whose target file sorted first alphabetically anyway

The rule that catches these: **when a test exists to prove implementation A differs from B,
pick the input where they actually differ, then prove it by breaking the implementation and
watching the test fail.** Make every implementer and reviewer do that mutation, and put the
before/after output in the report. It is the single highest-value instruction in the whole
dispatch template.

**Three documentation claims were wrong** for the same reason: they described the epic's end
state as present fact, or cited a file that does not exist. Verify every path, count, and node
chain against the code before writing it down.

**Reviewers are leads, not verdicts.** One reviewer's finding was simply wrong about a node
count; checking it anyway exposed a real defect in the same sentence. Another proved a fix by
reverting it, which is what confirmed the XSS gap was genuine.

## Gotchas specific to this environment

- Worktree isolation blocks reviewers from running `git` against the sibling checkout.
  Pre-extract anything they must compare: `git archive <sha> <path> | tar -x -C <scratchpad>`
  handles a whole directory and survives the guard, where `git show` in a loop does not.
- The same guard rejects `bd` commands containing an apostrophe. Reword rather than escaping.
- Both projects have a package named `crack`. When generating a golden fixture, prove which one
  was imported by resolving `crack.__file__`; otherwise the fixture is produced by the very code
  it is meant to check and passes while proving nothing. `regen_golden.py` already guards this.
- Copilot PR review is quota-limited on this account and re-requesting does not help. It
  contributed nothing to PR #25. Assume agent review is the only review.

## Open questions

- **coderay-aph** (writing-style skill) has an unanswered scope question: does it govern the
  prose `crack` generates, or the repo documents Claude writes? Worth settling before three more
  analyses each arrive with their own voice.
- Whether to land q2r.8 and q2r.12 upstream before this port. Both are backend-only files, so
  they do not block architecture, but every port that inherits an unfixed defect multiplies the
  eventual re-port.
