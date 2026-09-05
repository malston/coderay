# Running an epic unattended

Claude Code can work every open child of a beads epic without you driving each step: one branch and one PR per bead, two review passes, the findings fixed or filed, the PR merged, the bead closed, then the next one. This page is how to start it, what it does on each pass, and how to stop it.

The protocol itself lives in `.claude/commands/epic-loop.md`, which Claude Code exposes as the `/epic-loop` command. Edit that file to change the rules.

## Before you start

- **The epic exists and its children are real work.** `bd show <epic-id>` should list the beads you want done. Anything that is a keep-or-delete call or an open design question can stay in the list; the loop investigates it, writes a recommendation into the bead, tags it `human` (`bd tag <id> human`, listed by `bd human list`), and moves on without deciding.
- **`main` is green** (`make test`) and `gh auth status` works, since the loop pushes, opens PRs and merges. Your own checkout can be on any branch with any uncommitted work: the loop never touches it.
- **You are fine with Claude merging.** Every PR gets a `/code-review` pass, and a PR for a bead of priority P3 or higher gets the `/pr-review-toolkit:review-pr` agents as well; the Critical and Important findings are fixed before the merge, but no human reads the diff first. If you want to read them, remove the `gh pr merge` line from step 7 of the command file and merge by hand; the cleanup and the bead close stay.

Optional: put the protocol into the epic's DESIGN field as well (`bd update <epic-id> --design "..."`). `/epic-loop` checks there first and lets it override the command file, and `bd show` brings it back after a context compaction.

## Start it

Two lines in a Claude Code session opened in the repo:

```text
/epic-loop coderay-5wu
/goal Every open child of beads epic coderay-5wu is closed or tagged `human`, worked per /epic-loop; or stop after 80 turns
```

The first line loads the protocol and starts the first bead. The second sets the completion condition. After every turn, a small model checks the condition and either lets Claude continue, records the goal as achieved, or records it as impossible. While a review agent or a background command is still running, the check is skipped until a turn ends with nothing in flight, so reviews are never cut short. The turn clause is a safety bound; raise or lower it to taste.

## What one pass does

1. From the main checkout, fetches and creates a worktree for the bead under `.claude/worktrees/` on a fresh branch from `origin/main` (or from an open PR that touches the same files), syncs its venv, and runs the rest of the pass from there. If a worktree for the bead already exists, it is reused. Your checkout is never switched.
2. Claims the bead and re-reads it, trimming anything an earlier PR already fixed.
3. Writes the failing test, watches it fail, makes the smallest fix, mutates the guard, runs the suite. Every commit is gated on a green suite in the same command.
4. Pushes, opens the PR with a body that states what changed, what was left for you to decide, the red and green test counts, and what was verified by hand. Waits for CI.
5. Runs `/code-review <PR#> medium` against the PR's own diff, plus the applicable `review-pr` agents when the bead is P3 or higher. A P4 is small enough that the second pass costs more than it finds.
6. Fixes what is labelled Critical, Important or HIGH in one review commit and adds a "Review round" section to the PR body. Everything else becomes a P3 or P4 bead under the epic. Findings outside the bead's scope are filed, never fixed in that PR.
7. Merges with a merge commit, fetches, and once `origin/main` contains the branch removes the worktree and the local branch (the remote branch stays), closes the bead with a reason that names the PR, and starts the next one. Your local `main` catches up on your next `git pull`.

The first two passes on the 1.0.0 epic (PRs #41 and #42) were three commits and about 130 to 150 changed lines each, tests included.

## Watching it

- `bd list --status=in_progress` shows the bead being worked; `bd show <epic-id>` shows what is left.
- `gh pr list` shows the current PR. Its body is the record of decisions and the review round.
- The `◎ /goal active` indicator in the terminal shows how long the goal has run.
- Beads the loop filed carry "PR NN review" in their description, so `bd list --status=open` after a run tells you what it found and did not fix.

## Stopping and resuming

- `/goal clear` stops the loop after the current turn. The bead's worktree and branch stay on disk under `.claude/worktrees/`; the PR, if open, stays open. `git worktree list` shows what is there.
- If you close the terminal, `claude --resume` restores an active goal but resets its turn count, so an `or stop after N turns` clause starts over. Re-run `/epic-loop <epic-id>` in the resumed session if the protocol is not in the epic's DESIGN field.
- If Claude answers the goal check several turns in a row without using any tool, Claude Code prints a warning and hands control back to you with the goal still set. That usually means a bead needs a decision only you can make; read the last message, answer it, and the loop resumes.

## What the loop never does

- Decide a keep-or-delete or design question. Those get a recommendation and a `human` tag.
- Delete code that looks unused, or rewrite an implementation.
- Bump the version, tag, or cut a release. Those are yours once the epic is empty.
- Fix a review finding outside the current bead's scope. It files a bead instead.

## Adapting it for another repo

Copy `.claude/commands/epic-loop.md`. The parts specific to this repo are the test command (`uv run pytest tests/ -q`) and the venv sync (`uv sync --locked`). Check that `.claude/worktrees/` is ignored in the target repo (`git check-ignore -q .claude/worktrees`); here it is excluded by Claude Code's own entries in `.git/info/exclude`, which is per clone and not committed, so a fresh clone is covered only once Claude Code has written that block. The review commands, the fix-or-file rule and the decision-bead rule carry over unchanged.
