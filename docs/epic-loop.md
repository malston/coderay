# Running an epic unattended

Claude Code can work every open child of a beads epic without you driving each step: one branch and one PR per bead, two review passes, the findings fixed or filed, the PR merged, the bead closed, then the next one. This page is how to start it, what it does on each pass, and how to stop it.

The protocol itself lives in `.claude/commands/epic-loop.md`, which Claude Code exposes as the `/epic-loop` command. Edit that file to change the rules.

## Before you start

- **The epic exists and its children are real work.** `bd show <epic-id>` should list the beads you want done. Anything that is a keep-or-delete call or an open design question can stay in the list; the loop investigates it, writes a recommendation into the bead, flags it with `bd human`, and moves on without deciding.
- **`main` is green** (`make test`), the working tree is clean apart from the usual `.beads/interactions.jsonl`, and `gh auth status` works, since the loop pushes, opens PRs and merges.
- **You are fine with Claude merging.** Every PR gets a `/code-review` and a `/pr-review-toolkit:review-pr` pass, and the Critical and Important findings are fixed before the merge, but no human reads the diff first. If you want to read them, remove step 7 from the command file and merge by hand.

Optional: put the protocol into the epic's DESIGN field as well (`bd update <epic-id> --design "..."`). `/epic-loop` checks there first and lets it override the command file, and `bd show` brings it back after a context compaction.

## Start it

Two lines in a Claude Code session opened in the repo:

```text
/epic-loop coderay-5wu
/goal Every open child of beads epic coderay-5wu is closed or flagged with `bd human`, worked per /epic-loop; or stop after 80 turns
```

The first line loads the protocol and starts the first bead. The second sets the completion condition. After every turn, a small model checks the condition and either lets Claude continue, records the goal as achieved, or records it as impossible. While a review agent or a background command is still running, the check is skipped until a turn ends with nothing in flight, so reviews are never cut short. The turn clause is a safety bound; raise or lower it to taste.

## What one pass does

1. Fast-forwards local `main`, checks whether any open PR touches the same files, and branches from `main` or from that PR.
2. Claims the bead and re-reads it, trimming anything an earlier PR already fixed.
3. Writes the failing test, watches it fail, makes the smallest fix, mutates the guard, runs the suite. Every commit is gated on a green suite in the same command.
4. Pushes, opens the PR with a body that states what changed, what was left for you to decide, the red and green test counts, and what was verified by hand. Waits for CI.
5. Runs `/code-review <PR#> medium` and the four `review-pr` agents against the PR's own diff.
6. Fixes what is labelled Critical, Important or HIGH in one review commit and adds a "Review round" section to the PR body. Everything else becomes a P3 or P4 bead under the epic. Findings outside the bead's scope are filed, never fixed in that PR.
7. Merges, fast-forwards `main`, deletes the branch, closes the bead with a reason that names the PR, and starts the next one.

The first two passes on the 1.0.0 epic (PRs #41 and #42) were two to three commits and about 100 to 130 changed lines each, tests included.

## Watching it

- `bd list --status=in_progress` shows the bead being worked; `bd show <epic-id>` shows what is left.
- `gh pr list` shows the current PR. Its body is the record of decisions and the review round.
- The `◎ /goal active` indicator in the terminal shows how long the goal has run.
- Beads the loop filed carry "PR NN review" in their description, so `bd list --status=open` after a run tells you what it found and did not fix.

## Stopping and resuming

- `/goal clear` stops the loop after the current turn. Work on the current branch stays as it is; the PR, if open, stays open.
- If you close the terminal, `claude --resume` restores an active goal. Re-run `/epic-loop <epic-id>` in the resumed session if the protocol is not in the epic's DESIGN field.
- If Claude answers the goal check several turns in a row without using any tool, Claude Code prints a warning and hands control back to you with the goal still set. That usually means a bead needs a decision only you can make; read the last message, answer it, and the loop resumes.

## What the loop never does

- Decide a keep-or-delete or design question. Those get a recommendation and a `bd human` flag.
- Delete code that looks unused, or rewrite an implementation.
- Bump the version, tag, or cut a release. Those are yours once the epic is empty.
- Fix a review finding outside the current bead's scope. It files a bead instead.

## Adapting it for another repo

Copy `.claude/commands/epic-loop.md`. The parts specific to this repo are the test command (`uv run python -m pytest tests/ -q`), the git-transport form used for pushes, and the `.beads/interactions.jsonl` stash around branch switches. The review commands, the fix-or-file rule and the decision-bead rule carry over unchanged.
