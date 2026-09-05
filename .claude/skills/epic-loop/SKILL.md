---
name: epic-loop
description: Work every open child of a beads epic unattended in Claude Code. One worktree, branch and PR per bead, a failing test first with the guard mutated to prove it bites, a fresh-context review pass, serious findings fixed and the rest filed to a sibling findings epic, then the PR merged (or held for human approval with --hold) and the bead closed before the next one starts. Design and keep-or-delete questions get a recommendation and a `human` tag instead of a decision. Pairs with /goal for the completion condition and a turn budget stored in the epic. Invoke as /epic-loop EPIC-ID, with --hold to stop at ready-for-review instead of merging. Not for a single bead, an epic with no children, or work that needs a human decision at every step.
disable-model-invocation: true
---

# Epic loop

Work the open children of a beads epic, one at a time, until every one is closed, blocked on a held PR, or tagged `human`.

## Arguments

`$ARGUMENTS` is the epic id, optionally followed by `--hold`.

* `EPIC` is the first word.
* `HOLD` is true if `--hold` appears anywhere. In hold mode you never merge. You stop at ready-for-review and move on.

Run `bd show $EPIC` first. Its DESIGN field may carry epic-specific instructions, most often the order to work the children in and which beads pair into one PR. Follow those. If DESIGN carries a full loop protocol, that protocol wins over anything below.

## How the loop runs

The user drives this with `/goal`, which re-evaluates the condition after every turn, waits for background review agents before judging, and survives a resumed session. The goal line looks like:

```text
/goal Every open child of beads epic <epic-id> is closed, blocked on a held PR, or tagged `human`, worked per /epic-loop; or stop when the epic's turn counter reaches 80
```

The turn counter lives in the epic so a resumed session doesn't reset it. End every turn, whatever else happened in it, by reading the epic's notes with `bd show $EPIC --json`, replacing the `turns: N` line (or appending one if absent), and writing the whole notes field back with `bd update $EPIC --notes "..."`. Notes is a single field and the user keeps their own remarks in it, so never write only the counter.

If no goal is active, keep going anyway. End each turn by picking up the next bead, and stop only at the stop condition at the bottom of this file.

## Paths

`ROOT` is the main checkout, `git rev-parse --show-toplevel` run from where the session started. Worktrees live at `$ROOT/.claude/worktrees/<bead-id>`, always as absolute paths so a worktree is never created inside another. The main checkout belongs to the user. Never switch its branch, and never run a bare `git stash` (the stash stack is shared across worktrees).

## Findings epic

Review findings you don't fix go under a sibling epic, never under `$EPIC`. On the first filing of a run, look for an open epic titled `$EPIC review findings` with `bd list --type=epic`. If none exists, create it (`bd create "$EPIC review findings" --type epic`) and record its id in the PR body. Every finding filed there names the PR it came from in its description.

## Per bead

1. **Pick and isolate.** From `$ROOT`, `git fetch origin`. List open PRs from this loop (`gh pr list --label epic-loop --json number,headRefName,files`). For each held PR whose bead is blocked, check `gh pr view <n> --json state`. If it merged, remove its worktree and branch as in step 7 and `bd close` its bead with the PR number. Then pick the next open bead whose files don't overlap any still-open PR from this loop. If every remaining bead overlaps an open PR, report which PRs need to land and stop. Never base a worktree on another PR's branch. Create the worktree with `git worktree add --no-track -b <branch> $ROOT/.claude/worktrees/<bead-id> origin/main` (`--no-track` so `git push -u origin <branch>` works). If `git worktree list` already shows one for this bead, reuse it. `cd` into it, `uv sync --locked`, and run steps 2 to 6 from there.

2. **Claim and scope.** `bd update <id> --claim`. Re-read the bead. If an earlier PR already covered part of it, don't edit the bead's title or description. Write down exactly what you're dropping and why, and carry that into the PR body's "Trimmed" section and the bead's close reason. Batch beads that share a file into one PR and say so in the body.

3. **Test first.** Write the failing test, watch it fail for the right reason, make the smallest fix, then mutate the guard both ways and watch the test go red each time before restoring it. After a mutation round, `rm -rf src/**/__pycache__` before trusting the suite. A same-size restore in the same second leaves a stale `.pyc` and the suite passes against the mutated code. Run the full suite (`uv run pytest tests/ -q`, the same command as `make test`). Gate every commit with `&&` on a pytest grep, since `set -e` doesn't abort in this tool. Edit files with Python, not `sed -i`.

4. **Open the PR.** `git push -u origin <branch>`, then `gh pr create --label epic-loop` with these sections: what changed, trimmed (what was dropped from the bead and why, or "nothing"), decisions left for the user, tests (red and green counts, mutations), verified by hand, what stays as is. Wait for CI in two steps. `gh pr checks <n> --watch` on its own returns at once before CI has registered the run, so first poll until the check exists (`until gh pr checks <n> | grep -q pytest; do sleep 10; done`), then `gh pr checks <n> --watch`.

5. **Review in a fresh context.** Dispatch a subagent whose entire prompt is the PR number and the instruction to run `/code-review <n> medium` against `gh pr diff <n>` and `git show origin/<branch>:<path>`, never the working tree. Pass it nothing from this session. Its output is the review. If the PR carries a bead of priority P0, P1, P2 or P3, also run `/pr-review-toolkit:review-pr <n>` with the same read-from-remote instruction. A PR whose beads are all P4 stops at the fresh-context `/code-review`. Stay in the bead's worktree until its fixes are pushed.

6. **Fix or file.** Fix every finding the reviews label Critical, Important or HIGH, and any finding that is a correctness or security defect whatever its label, in one review commit. Re-run checks. Add a "Review round" section to the PR body. File everything else under the findings epic after `bd search` for a duplicate, P3 for behavioural, P4 for style or simplification, with "PR <n> review" in the description. Findings outside the bead's scope are filed, never fixed in this PR.

7. **Land or hold.**
   * Merge mode: `gh pr merge <n> --merge` (a merge commit, not a squash, so the branch tip stays reachable from `origin/main`). Back in `$ROOT`, `git fetch origin`. Once `git branch -r --contains <branch>` lists `origin/main`, `git worktree remove $ROOT/.claude/worktrees/<bead-id>` and `git branch -D <branch>`. The remote branch stays. `bd close <id> --reason="PR <n>: ..."` including any trim, then `bd show <id>` to confirm the status changed. Then the next bead.
   * Hold mode: `gh pr ready <n>` if it's a draft. `bd update <id> --status blocked` and append a line `held: PR <n>` to the bead's notes, preserving whatever is already there. Leave the worktree and branch in place. Then the next non-overlapping bead. The cleanup and close happen in step 1 of a later pass once the PR has merged.

## Decision beads

A bead that asks whether to keep or delete code, or that has an open design question, isn't yours to decide. Investigate, write the recommendation with `bd update <id> --notes`, run `bd tag <id> human` (listed by `bd human list`; `bd human <id>` on its own only prints a help menu), and move on. Never delete code that seems unused or rewrite an implementation without the user.

## Never

* Edit a bead's title or description. Trims go in the PR body and close reason.
* Overwrite a notes field. Read it, change your line, write the whole thing back.
* Base a worktree on another PR's branch.
* File a finding under `$EPIC`.
* Review a diff from the session that wrote it.
* Merge in hold mode.
* Bump the version, tag, or cut a release.

## Stop

When every child of `$EPIC` is closed, blocked on a held PR, or tagged `human`, report the state in a few lines. Name the findings epic id and how many beads it holds, and in hold mode list the PRs waiting for approval. Then stop.
