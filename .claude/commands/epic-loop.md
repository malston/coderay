---
description: Work every open child of a beads epic unattended, one PR each, both reviews, merge, next. Pair with /goal.
---

Work the open children of beads epic `$ARGUMENTS`, one at a time, until every one is closed or tagged `human`. Run `bd show $ARGUMENTS` first: if its DESIGN field carries a loop protocol, that protocol wins over anything below.

Mark drives this with `/goal`, which re-evaluates the condition after every turn, waits for background review agents before judging, and survives a resumed session. The line he types after this command is:

```text
/goal Every open child of beads epic $ARGUMENTS is closed or tagged `human`, worked per /epic-loop; or stop after 80 turns
```

If no goal is active, keep going anyway: end each turn by picking up the next bead, and stop only at the stop condition below.

## Per bead

1. `git fetch origin`, then give the bead its own worktree: `git worktree add -b <branch> .claude/worktrees/<name> origin/main`, `uv sync --locked` there, and run every command from that directory. The main checkout belongs to Mark; never switch its branch, and never run a bare `git stash` (the stash stack is shared across worktrees). Check open PRs (`gh pr list`, `gh pr diff <n> --name-only`) for the files this bead touches; if one overlaps, base the worktree on that PR head and open with `--base <that branch>`, and say so in the PR body.
2. `bd update <id> --claim`. Re-read the bead; trim anything an earlier PR already fixed. Batch beads that share a file into one PR.
3. Test first. Write the failing test, watch it fail for the right reason, make the smallest fix, mutate the guard both ways, run the full suite (`uv run pytest tests/ -q`, the same command as `make test`). Gate every commit with `&&` on a pytest grep, since `set -e` does not abort in this tool. Edit files with Python, not `sed -i`.
4. Push and `gh pr create` with these sections: what changed, decisions left for Mark, tests (red and green counts, mutations), verified by hand, what stays as is. Wait for `gh pr checks <n> --watch`.
5. Run `/code-review <PR#> medium` and `/pr-review-toolkit:review-pr <PR#>`. Tell every review agent to read `gh pr diff <n>` and `git show origin/<branch>:<path>`, never the working tree. Stay on the PR branch until its fixes are pushed.
6. Fix every finding labelled Critical, Important or HIGH, and any correctness or security defect, in one review commit; re-run checks; add a "Review round" section to the PR body. File everything else as beads under `$ARGUMENTS` after `bd search` for a duplicate: P3 for behavioural, P4 for style or simplification. Findings outside the bead's scope are filed, not fixed.
7. `gh pr merge <n> --merge`, then `git worktree remove .claude/worktrees/<name>` and `git branch -D <branch>` once `git branch -r --contains <branch>` shows `origin/main`, `bd close <id> --reason="PR <n>: ..."`. Leave Mark's `main` checkout alone; it catches up on his next `git pull`. Then the next bead.

## Decision beads

A bead that asks whether to keep or delete code, or that has an open design question, is not yours to decide. Investigate, write the recommendation into `bd update <id> --notes`, run `bd tag <id> human` (which `bd human list` then shows), and move on. Never delete code that seems unused or rewrite an implementation without Mark.

## Stop

When every child is closed or tagged `human`, report the state in a few lines and stop. Version bumps, tags and releases are Mark's, not the loop's.
