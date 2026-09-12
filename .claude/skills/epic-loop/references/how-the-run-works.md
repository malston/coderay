# How the run works

The plumbing behind `/epic-loop`. Read this when the driver misbehaves, when
you want to start a run from a plain shell, or when you are changing the
driver. Nobody needs it to use the skill.

## The two calls

A run is two `claude` calls against one session id, in this order.

```bash
SID="$(uuidgen)"

claude -p "/goal <condition>" --session-id "$SID" --max-turns 1 \
    --disallowedTools "Bash,Edit,Write,NotebookEdit,Task,Agent"

claude -p "/epic-loop <bead-id> [--hold] --worker" --resume "$SID" \
    --permission-mode bypassPermissions --max-turns 400
```

Both are required, and the order matters, for three reasons.

The CLI expands only the **first** slash command in a prompt. Everything after
it becomes that command's arguments, so a `/goal` on a later line is dead text.
The two cannot share one call.

The skill sets `disable-model-invocation: true`, so the model will not reach
either command on its own. They have to be typed.

The arming call is denied every tool that can change the repository and capped
at one turn. Without that it starts satisfying the goal in the arming call
itself, working beads before the loop protocol is loaded. The goal is still
recorded, and it survives both the cap and the denial.

The condition to arm:

```text
/goal Every open child of beads epic <bead-id> is closed, blocked on a held PR, or tagged `human`, worked per /epic-loop; or stop when the epic's turn counter reaches 20
```

The backticks around `human` must stay literal. In a shell that builds this
string, escape them. Unescaped, bash runs `human` as a command, the
substitution yields nothing, and the condition quietly loses the word, which is
how a human-tagged bead stops counting as settled.

## The run marker

`--worker` on the second call tells the skill the session is the run. Without
it the skill starts a run instead of working beads, which is exactly what it
should do when a person types `/epic-loop` in their own session. A working call
that lost the marker would spawn a driver, which would spawn a driver.

To work an epic in your own interactive session rather than a background one,
arm the goal with `/goal <condition>` and then type `/epic-loop <bead-id>
--worker`. The marker is what tells the skill you meant this session. Expect to
prompt it between beads: a session yields to you at the end of every turn, and
only the `-p` calls above run unattended.

## Two different budgets

`--max-turns` is Claude Code's own cap on the working call, a runaway stop. The
loop spends turns fast: one bead runs a failing test, a mutation round, a PR, a
fresh-context review and a fix commit.

The turn counter in the goal condition is a different number. It lives in the
parent bead's notes so a resumed session does not reset it, and the skill
rewrites it at the end of every turn.

## The API key

Both calls run from inside the target repository. A repository that exports an
Anthropic key for its own tooling -- a direnv `.envrc`, a sourced `.env` -- or a
shell that exports one globally, hands it to `claude` too, where it outranks
the claude.ai login. The run then bills a pay-as-you-go account and can die on
"Credit balance is too low" before working a single bead.

The driver strips `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from both
calls. Set `EPIC_LOOP_KEEP_API_KEY=1` when that account is the one you mean to
spend. **Typing the calls by hand carries the same risk**, so prefix them with
`env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN`.

## The driver

`scripts/epic-loop` assembles both calls. Run it from anywhere; the target repo
comes from `--repo`, or from the git root of the current directory.

```
epic-loop BEAD-ID [options]

  --hold               Stop each bead at ready-for-review; never merge
  --repo DIR           Target repository (default: git root of $PWD)
  --dry-run            Print the exact calls and exit; spends nothing
  --budget USD         Max API spend (default: 200.00)
  --max-turns N        Claude Code turn cap for the working call (default: 400)
  --turn-budget N      Parent's turn counter the goal stops at (default: 20)
  --model NAME         Model (default: claude-opus-5)
  --log-dir DIR        Run logs (default: ~/.local/state/epic-loop)
  --session-id UUID    Reuse a session id instead of generating one
```

It takes any bead with children -- an epic, a feature, a task with subtasks.
What matters is that there are children to work, not what the parent is called.

Before spending anything it refuses a bead that does not exist, is closed, has
no children, or whose children are all settled. It refuses to run from a linked
worktree, since the skill creates worktrees under the main checkout and must
not nest them. It checks that `claude`, `bd`, `gh`, `jq`, `git` and `uuidgen`
are all present.

It logs each run and prints the resume command when a cap stops it. Exit status
is the status of the working call; nonzero usually means a cap, not a fault.

### bd's JSON shapes

`bd` returns a bare object, a single-element array, or -- since 1.2, which
stamps `schema_version` -- a `{"data": ..., "schema_version": N}` envelope
around either. A failure is a third shape: `{"error": ..., "schema_version": N}`
with no `data` key at all. The driver's unwrapper requires both keys before it
takes `.data`, so an error object survives intact and stays readable.

## The test

`scripts/epic-loop-test` proves the driver still assembles both calls
correctly. It stubs `claude`, so it spends nothing and touches no repository,
and it cleans up the throwaway beads it creates in the target tracker.

```bash
epic-loop-test                          # against the current repo
epic-loop-test --repo ~/code/otherproj  # against another beads workspace
epic-loop-test --driver ./scripts/epic-loop
epic-loop-test --keep                   # leave the fixtures for inspection
```

Run it after editing the driver. It refuses to start unless `claude` resolves
to its own stub, since a shadowed stub would run the real thing against a real
repository with `bypassPermissions`.
