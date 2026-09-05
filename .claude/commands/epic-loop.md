---
description: Work every open child of a beads epic unattended, one PR each, reviewed to the bead's priority, merge, next. Pair with /goal.
---

Work the open children of beads epic `$ARGUMENTS`, one at a time, until every one is closed or tagged `human`. Run `bd show $ARGUMENTS` first: if its DESIGN field carries a loop protocol, that protocol wins over anything below.

Mark drives this with `/goal`, which re-evaluates the condition after every turn, waits for background review agents before judging, and survives a resumed session. The line he types after this command is:

```text
/goal Every open child of beads epic $ARGUMENTS is closed or tagged `human`, worked per /epic-loop; or stop after 80 turns
```

If no goal is active, keep going anyway: end each turn by picking up the next bead, and stop only at the stop condition below.

## Per bead

1. From the main checkout (`/Users/markalston/code/coderay`): `git fetch origin`, then give the bead its own worktree with `git worktree add --no-track -b <branch> /Users/markalston/code/coderay/.claude/worktrees/<name> origin/main` (absolute path, so a worktree is never created inside another; `--no-track`, so the branch does not track `origin/main` and `git push -u origin <branch>` works). If `git worktree list` already shows a worktree for this bead, use it. `cd` into it, `uv sync --locked`, and run steps 2 to 6 from there. The main checkout belongs to Mark; never switch its branch, and never run a bare `git stash` (the stash stack is shared across worktrees). Check open PRs (`gh pr list`, `gh pr diff <n> --name-only`) for the files this bead touches; if one overlaps, base the worktree on that PR head and open with `--base <that branch>`, and say so in the PR body.
2. `bd update <id> --claim`. Re-read the bead; trim anything an earlier PR already fixed. Batch beads that share a file into one PR.
3. Test first. Write the failing test, watch it fail for the right reason, make the smallest fix, mutate the guard both ways, run the full suite (`uv run pytest tests/ -q`, the same command as `make test`). Gate every commit with `&&` on a pytest grep, since `set -e` does not abort in this tool. Edit files with Python, not `sed -i`.
4. `git push -u origin <branch>` and `gh pr create` with these sections: what changed, decisions left for Mark, tests (red and green counts, mutations), verified by hand, what stays as is. Wait for `gh pr checks <n> --watch`.
5. Run `/code-review <PR#> medium`. If the PR carries a bead of priority P0, P1, P2 or P3, also run `/pr-review-toolkit:review-pr <PR#>`; a PR whose beads are all P4 stops at `/code-review`. Tell every review agent to read `gh pr diff <n>` and `git show origin/<branch>:<path>`, never the working tree. Stay in the bead's worktree until its fixes are pushed.
6. Fix every finding the reviews label Critical, Important or HIGH, and any finding that is a correctness or security defect whatever its label, in one review commit; re-run checks; add a "Review round" section to the PR body. File everything else as beads under `$ARGUMENTS` after `bd search` for a duplicate: P3 for behavioural, P4 for style or simplification. Findings outside the bead's scope are filed, not fixed.
7. `gh pr merge <n> --merge` (a merge commit, not a squash, so the branch tip stays reachable from `origin/main`). Back in the main checkout: `git fetch origin`; once `git branch -r --contains <branch>` lists `origin/main`, `git worktree remove /Users/markalston/code/coderay/.claude/worktrees/<name>` and `git branch -D <branch>`; the remote branch stays unless you `git push origin --delete <branch>`. `bd close <id> --reason="PR <n>: ..."`. Leave Mark's `main` checkout on whatever branch it is; it catches up on his next `git pull`. Then the next bead.

## Decision beads

A bead that asks whether to keep or delete code, or that has an open design question, is not yours to decide. Investigate, write the recommendation into `bd update <id> --notes`, run `bd tag <id> human` (which `bd human list` then shows), and move on. Never delete code that seems unused or rewrite an implementation without Mark.

## Stop

When every child is closed or tagged `human`, report the state in a few lines and stop. Version bumps, tags and releases are Mark's, not the loop's.
