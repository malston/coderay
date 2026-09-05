---
name: epic-loop
description: Work every open child of a beads epic unattended in Claude Code. One worktree, branch and PR per bead, a failing test first with the guard mutated to prove it bites, a fresh-context review pass, serious findings fixed and the rest filed to a sibling findings epic, then the PR merged (or held for human approval with --hold) and the bead closed before the next one starts. Design and keep-or-delete questions get a recommendation and a `human` tag instead of a decision. Pairs with /goal for the completion condition and a turn budget stored in the epic. Use when Mark says "run the epic", "work the epic", "epic loop", "burn down these beads", names a beads epic id and wants it done end to end, or asks to leave Claude Code running on a list of issues overnight. Not for a single bead, an epic
---

# Running an epic unattended

Claude Code can work every open child of a beads epic without you driving each step. One branch and one PR per bead, a fresh-context review pass, the findings fixed or filed, the PR merged or handed to you, the bead closed, then the next one. This page is how to start it, what it does on each pass, what keeps it bounded, and how to stop it.

The protocol itself lives in `.claude/commands/epic-loop.md`, which Claude Code exposes as the `/epic-loop` command. Edit that file to change the rules.

## Before you start

* **The epic exists and its children are real work.** `bd show <epic-id>` should list the beads you want done. Anything that is a keep-or-delete call or an open design question can stay in the list. The loop investigates it, writes a recommendation into the bead, tags it `human` (`bd tag <id> human`, listed by `bd human list`), and moves on without deciding.
* **`main` is green** (`make test`) and `gh auth status` works, since the loop pushes and opens PRs. Your own checkout can be on any branch with any uncommitted work. The loop never touches it.
* **You've picked a merge mode.** `/epic-loop <epic-id>` merges each PR itself once review is clean. `/epic-loop <epic-id> --hold` stops at ready-for-review and leaves the merge to you. Use `--hold` in any repo with branch protection or a policy that a person approves every change. The review, the fix-or-file rule and the bead bookkeeping are the same in both modes. Only step 7 differs.
* **A findings epic exists, or you're fine with the loop creating one.** Review findings the loop doesn't fix are filed as beads under a sibling epic named `<epic-id> review findings`, never under the epic being worked. See "Why findings go to a sibling epic" below.

Optional: put the protocol into the epic's DESIGN field as well (`bd update <epic-id> --design "..."`). `/epic-loop` checks there first and lets it override the command file, and `bd show` brings it back after a context compaction.

## Start it

Two lines in a Claude Code session opened in the repo:

```
/epic-loop coderay-5wu
/goal Every open child of beads epic coderay-5wu is closed or tagged `human`, worked per /epic-loop; or stop when the epic's turn counter reaches 80
```

The first line loads the protocol and starts the first bead. The second sets the completion condition. After every turn, a small model checks the condition and either lets Claude continue, records the goal as achieved, or records it as impossible. While a review agent or a background command is still running, the check is skipped until a turn ends with nothing in flight, so reviews are never cut short.

The turn counter lives in the epic, not the session. At the end of every turn the loop increments `turns` in the epic's notes (`bd update <epic-id> --notes "turns: N"`), and the goal clause reads that number. A session restart doesn't reset it. Raise or lower the bound to taste, and reset the counter by hand (`--notes "turns: 0"`) when you want a fresh budget.

## What one pass does

1. From the main checkout, picks the next open bead whose files don't overlap an open PR from this loop, fetches, and creates a worktree for it under `.claude/worktrees/` on a fresh branch from `origin/main`. Syncs its venv and runs the rest of the pass from there. If a worktree for the bead already exists, it's reused. Your checkout is never switched. If every remaining bead overlaps an open PR, the loop stops and tells you which PRs need to land first. It doesn't stack branches.
2. Claims the bead and re-reads it. If an earlier PR already covered part of the bead, the loop records exactly what it's dropping as a bead comment (`bd comment <id> "Trimmed: ... already done in PR NN"`) before doing any work, and repeats the trim in the PR body. The bead's own text is never edited by the loop.
3. Writes the failing test, watches it fail, makes the smallest fix, mutates the guard and watches the test go red again, restores it, runs the suite. Every commit is gated on a green suite in the same command. The mutation step is what proves the test bites. Skip it and you get green suites that assert nothing.
4. Pushes, opens the PR with a body that states what changed, what was trimmed from the bead and why, what was left for you to decide, the red and green test counts, and what was verified by hand. Waits for CI.
5. Runs review in a fresh context. Every PR gets `/code-review <PR#> medium` from a subagent that hasn't seen the implementation session, so the reviewer doesn't inherit the author's assumptions about what the diff does. A PR carrying a bead of priority P0 to P3 also gets the `/pr-review-toolkit:review-pr` agents. A PR whose beads are all P4 stops at the fresh-context `/code-review`.
6. Fixes what is labelled Critical, Important or HIGH in one review commit, re-runs the suite, and adds a "Review round" section to the PR body. Everything else becomes a P3 or P4 bead under the sibling findings epic. Findings outside the bead's scope are filed, never fixed in that PR.
7. In merge mode, merges with a merge commit, fetches, and once `origin/main` contains the branch removes the worktree and the local branch (the remote branch stays), closes the bead with a reason that names the PR, and starts the next one. Your local `main` catches up on your next `git pull`. In `--hold` mode, marks the PR ready for review, applies the `epic-loop` label, sets the bead to `blocked` with the PR number in the reason, and moves to the next non-overlapping bead. On later passes, any held PR that has since merged gets its worktree cleaned up and its bead closed.

The first two passes on the 1.0.0 epic (PRs #41 and #42) were three commits and about 130 to 150 changed lines each, tests included.

## Why findings go to a sibling epic

An earlier version filed review findings under the epic being worked. Since the goal is "every open child is closed," each PR could add children and extend the run. A reviewer's taste on pass 12 was shaping what got built on pass 25, with nobody in between. Filing to `<epic-id> review findings` keeps the run bounded by the work you asked for. When the loop finishes, `bd show <findings-epic-id>` is a list of what it saw and chose not to fix, and you decide whether to run the loop again on that epic.

## Watching it

* `bd list --status=in_progress` shows the bead being worked. `bd show <epic-id>` shows what is left and the current turn counter.
* `gh pr list --label epic-loop` shows PRs the loop opened. In `--hold` mode this is your review queue. Each body is the record of decisions, trims and the review round.
* The `◎ /goal active` indicator in the terminal shows how long the goal has run.
* `bd show <findings-epic-id>` lists what the loop found and did not fix. Each bead's description names the PR its finding came from.

## Stopping and resuming

* `/goal clear` stops the loop after the current turn. The bead's worktree and branch stay on disk under `.claude/worktrees/`. The PR, if open, stays open. `git worktree list` shows what is there.
* If you close the terminal, `claude --resume` restores an active goal. The turn counter is read from the epic, so the budget picks up where it left off. Re-run `/epic-loop <epic-id>` in the resumed session if the protocol isn't in the epic's DESIGN field.
* If Claude answers the goal check several turns in a row without using any tool, Claude Code prints a warning and hands control back to you with the goal still set. That usually means a bead needs a decision only you can make, or every remaining bead is waiting on a held PR. Read the last message, answer it or merge, and the loop resumes.

## What the loop never does

* Decide a keep-or-delete or design question. Those get a recommendation and a `human` tag.
* Edit a bead's text. Trims are comments, and the bead stays as you wrote it.
* Delete code that looks unused, or rewrite an implementation.
* Branch from another open PR. Overlapping work waits.
* File a finding under the epic it's working.
* Review its own diff from the session that wrote it.
* Bump the version, tag, or cut a release. Those are yours once the epic is empty.
* Fix a review finding outside the current bead's scope. It files a bead instead.

## Adapting it for another repo

Copy `.claude/commands/epic-loop.md`. The parts specific to this repo are the test command (`uv run pytest tests/ -q`) and the venv sync (`uv sync --locked`). Check that `.claude/worktrees/` is ignored in the target repo (`git check-ignore -q .claude/worktrees`). Here it's excluded by Claude Code's own entries in `.git/info/exclude`, which is per clone and not committed, so a fresh clone is covered only once Claude Code has written that block. Create the `epic-loop` label once (`gh label create epic-loop`). The review commands, the fix-or-file rule, the decision-bead rule and the sibling findings epic carry over unchanged. Default to `--hold` when you're not the only person who merges to that repo.
