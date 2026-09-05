# Contributing

## Setup

```bash
make install       # uv sync --locked
cp .env.example .env
```

Add one API key to `.env`. See `.env.example` for the full list of keys. You need a key only to run the pipeline against a real repo (`crawl tour path/to/repo`). The test suite needs no key and no network access.

## Running tests

```bash
make test          # uv run pytest tests/ -q
```

The tests fake LLM (large language model) calls at the `call_llm`/`yaml_call` boundary. See `tests/conftest.py`. The tests do not mock code deeper in the call stack. CI (continuous integration) runs the same test suite on every push and pull request. See `.github/workflows/tests.yml`.

## Making a change

This codebase follows a few conventions. See `CLAUDE.md` for the full list.

* Parse LLM YAML output through `crawl.core.yaml_call`. This function retries with a varied prompt when it gets a bad response. Do not add a new parse-and-retry loop in `src/crawl/analyses/tour/nodes.py`.
* Escape untrusted input before it reaches HTML or Mermaid output. Untrusted input includes the target repo's own files. It also includes anything the LLM echoes back from those files. `src/crawl/analyses/tour/render.py` once had a confirmed stored-XSS (cross-site scripting) bug here. Read `.full-review/02a-security.md` before you change that file's rendering code.
* Enforce a file-content budget (`preview_budget`, `codebase_budget`) by capping how many files the pipeline includes. Do not enforce the budget by raising a per-file floor instead. The per-file-floor approach caused two scalability bugs in the past.
* Add a new output lens by adding one file to `src/crawl/analyses/tour/instructions/`. This step needs no code change and no registration step.

This project has no linter and no formatter configured. Match the style of the surrounding code.

## Pull requests

Keep test output clean. When a test triggers an error on purpose, assert on that error's output. Do not let the error print unchecked. Open your pull request against the `main` branch. CI must pass before a merge.

## Tracking work

Issues live in the repo under `.beads/` and are managed with the `bd` command (Beads). `bd list --status=open` shows what is open, `bd show <id>` shows one issue with its notes and design field, and `bd human list` shows the issues waiting on a decision from a person. Larger pieces of work are epics with child issues. Claude Code sessions in this repo load the `beads` skill from `.claude/skills/beads/` and use `bd` the same way.

## Working an epic unattended

The `/epic-loop` skill in `.claude/skills/epic-loop/SKILL.md` lets Claude Code work every open child of an epic on its own. Each child gets a worktree under `.claude/worktrees/`, a failing test first, a pull request, a review from a fresh-context subagent, and either a merge or a hand-off to you. Design and keep-or-delete questions get a written recommendation and a `human` tag instead of a decision.

To start it, open Claude Code in the repo with `main` green and `gh auth status` working, then type two lines. The first loads the protocol, the second sets the completion condition.

```text
/epic-loop <epic-id>
/goal Every open child of beads epic <epic-id> is closed, blocked on a held PR, or tagged `human`, worked per /epic-loop; or stop when the epic's turn counter reaches 80
```

Add `--hold` to the first line (`/epic-loop <epic-id> --hold`) to stop each pull request at ready-for-review and leave the merge to you. Use this in any repo where a person is required to approve every change.

To watch it, `bd list --status=in_progress` shows the issue being worked, `gh pr list --label epic-loop` shows the pull requests the loop has opened (and, in hold mode, your review queue), and `bd show <epic-id>` shows what is left plus the turn counter in its notes. Review findings the loop did not fix are filed as issues under a sibling epic titled `<epic-id> review findings`.

To stop it, `/goal clear` ends the loop after the current turn. Worktrees and open pull requests stay where they are. If you close the terminal, `claude --resume` restores the goal and the turn counter picks up from the epic. If Claude answers the goal check a few turns in a row without doing anything, Claude Code hands control back to you. That usually means an issue needs a decision only you can make, or every remaining issue is waiting on a held pull request.

Epic-specific instructions such as the order to work children in go in the epic's design field (`bd update <epic-id> --design "..."`). The loop reads that first.

## Full architecture writeup

`README.md` covers the pipeline and the CLI (command-line interface) from a user's point of view. `.full-review/*.md` holds a full code review of the whole codebase. The fixes from that review are already on `main`. Read the review before you make a non-trivial change.
