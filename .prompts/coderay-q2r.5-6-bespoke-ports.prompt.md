# Handoff: coderay-q2r.5 and q2r.6 — the two bespoke-renderer ports

## Where things stand

`main` is at `b2f9fd2`. PR #27 merged: `architecture`, `interfaces` and `schema` all ship,
the port source is frozen, and `crack` now dispatches five analyses
(`tour`, `backend`, `architecture`, `interfaces`, `schema`). 514 tests, no network, no API key.

`bd ready` for the remaining work. The two ports left are **not** card-family, which is why
they were sequenced last.

## Read these first, in this order

1. `docs/superpowers/specs/2026-09-01-analysis-port-design.md` — the approach and decision record.
2. `docs/superpowers/plans/2026-09-01-backend-analysis-port.md` — the task template. Tasks 1-5
   are long done; a port is tasks 6-9 only.
3. `CLAUDE.md`, "Conventions & Patterns". Two rules bite on every port: LLM YAML goes through
   `crack.core.yaml_call`, and a file budget is enforced by capping **how many files** are
   included, never by shortening each one.

## The port source is FROZEN

Pinned at `34f0ad2a7044284555911590ca3773c92e1244ac` on the sibling's `main`
(`~/code/Crack-Any-Codebase-with-AI`). `scripts/regen_golden.py` enforces the pin and refuses
to run against anything else. Do not move it. Read pinned files without checking the sibling out:

```bash
git -C ~/code/Crack-Any-Codebase-with-AI show 34f0ad2:<path>
git -C ~/code/Crack-Any-Codebase-with-AI archive 34f0ad2 <dir> | tar -x -C <scratchpad>
```

Freezing ended the old "characterize here, fix upstream, re-port" loop. **Mark's standing
decision: inherited defects are now fixed in coderay**, each kept to a single named seam with a
bead reference in a comment, so a re-port stays mechanical. Seven such seams already exist;
`arch_crawl._redact` and `crack.core.within_repo` are the models to copy.

## What makes these two different

Both declare `render_html` / `render_markdown` themselves, and `crack/core/render.py` steps
aside for them (`getattr(analysis, "render_html", None)`). Neither imports the card engine at
all — verified, zero `from crack.core` imports in either `render.py`. So:

- **No `SECTIONS`, no `THEME`.** Do not try to force them into the card family.
- **`regen_golden.py` reaches them fine** — `crack.core.render.render_html` delegates to a
  custom `render_html` when the analysis declares one, so the script needs no change to CALL
  them. (An earlier draft of this handoff said these "bypass" `crack.core.render`. That is
  false; verified against `render_html` in both trees.)
- **But `_apply_divergences` will refuse to run.** It requires EVERY `DIVERGENCES` entry to
  match the rendered HTML and `sys.exit`s otherwise. The card engine's mermaid line ends
  `securityLevel: 'loose', flowchart: { htmlLabels: true } });`; `git_history/render.py`
  renders `securityLevel: 'loose' });` with no flowchart option, so the existing entry cannot
  match. Divergences have to become per-analysis before either fixture can be generated. Note
  the entries match RENDERED output, and these renderers are `.format` templates, so `{{` in
  the source is `{` in the output — key new entries off actual output, not the file.

| Bead | Analysis | Files | Notable |
| --- | --- | --- | --- |
| q2r.5 | `git-history` | 6 files, ~1050 lines (`render.py` alone is 508) | `--max-graves`, `--grave-min-files`; reads git via `subprocess` |
| q2r.6 | `product-intent` | 7 files, ~1000 lines (`render.py` is 544) | `--include`/`--exclude`; **needs `call_image`** |

## Two blockers to settle BEFORE writing code

**1. `product_intent.init_shared` needs `out_dir`, and coderay's contract does not pass it.**

Upstream: `init_shared(args, out_dir)`, because `IllustratePain` writes `pain.png` beside the
report and takes the path from `shared["pain_image_path_target"]`. Every previous port converted
`init_shared` to one argument, which is a sanctioned adaptation — that conversion is not
available here. `run_analysis` (`src/crack/core/runner.py:33`) already computes `out_dir` and
creates it before the flow runs, so the data exists; the signature just does not carry it.

This is an interface change to shared core that affects all five shipping analyses. **Ask Mark
before choosing.** Options worth putting to him: pass `out_dir` to every `init_shared`; accept
either arity by inspection; or put `out_dir` into `shared` after `init_shared` returns.

**2. `product_intent` imports `crack.core.call_image`, which coderay does not have.**

Upstream keeps it in `core/call_llm.py`; coderay's copy of that file already differs by ~293
lines (it is coderay's own module, with the streaming fix and the pricing work). Porting
`call_image` means adding an image-generation path — Gemini — to shared core. `IllustratePain`
is explicitly optional upstream: no `GEMINI_API_KEY` means no image, `shared["pain_image_path"]`
is None, and the renderer omits it cleanly. **Confirm with Mark** whether to port the image path
at all or ship `product-intent` text-only for now. Text-only is a real option and much smaller.

**3. `git_history/nodes.py` imports `crack.core.json_call`, which coderay does not have.**

Upstream keeps `parse_json` and `json_call` in `core/llm.py` beside `parse_yaml`/`yaml_call`;
coderay has only the YAML pair. `json_call` mirrors `yaml_call` almost exactly, so this is a
small additive port rather than a decision — but it IS shared-core work, and an earlier draft
of this handoff claimed q2r.5 had no blockers. It does.

While porting it: widen the catch tuple to include `TypeError` and `AttributeError`.
`NameEras.normalize` does `k in e` over the parsed list, and an int there raises `TypeError`
straight through both retry layers — the same crash class as coderay-q2r.18. `yaml_call` has
the identical gap; the PR #27 review said the root fix belonged there and it was patched at the
call site instead. Fix both.

`git-history` needs no interface change and no image path, so it is still the smaller of the
two. **Take q2r.5 first.**

`src/crack/core/index.py` exists upstream and not here. It is the landing page for a `crack all`
command coderay does not have. Out of scope for both beads; do not port it as a side effect.

## Process that has earned its keep

Use `superpowers:subagent-driven-development` for the port itself, then **review before you open
the PR, not after**. PR #27 was reviewed by four specialists plus a Codex adversarial pass, and
the reviews found two credential-disclosure paths, a crash, and an arbitrary-file-read — after
I had already called the work done. Budget for that.

**The single highest-value instruction: every test that exists to prove implementation A differs
from naive implementation B must be proved by breaking the implementation and watching it fail.**
Put the before/after counts in the report. Two things this catches, both of which happened:

- A mutation that "passes" may mean your edit never landed. Assert the file changed
  (`git diff --stat`) before concluding a test is weak.
- A test that reads a committed fixture off disk guards bytes, not behaviour. Two shipped in
  #27 and had to be fixed; render live instead.

**Mutate in BOTH directions.** The `q2r.14` redactor shipped with five green mutations and still
destroyed Docker Compose's `secrets:` block, because every mutation asked whether redaction was
strong enough and none asked whether it was too strong. For any guard, test that it fires AND
that it leaves the legitimate case alone.

**Verify claims against the code before writing them down.** Seventeen false documentation claims
have been caught across two PRs — wrong counts, "the only analysis that…" superlatives that were
not, and beads cited as open that were closed. Check every path, count, node chain and
`coderay-q2r.NN` reference with `bd show` before committing prose.

## Known-defect beads still open, now coderay's to fix

`q2r.10` (architecture blind to CDK/Pulumi/SAM), `q2r.12` (backend never classifies a flat
Django `views.py`), `q2r.13` (`OverviewNode` swallows its exception, so a failed overview is
silent), `q2r.15` (`git grep` failure indistinguishable from no SDK imports).

`q2r.13` is worth doing alongside these two: both new analyses use `OverviewNode`, so the silent
failure gets two more expensive call sites. Each of the four has a characterization test that
asserts the defect and flips when it is fixed — find them with `grep -rn "coderay-q2r\." tests/`.

## Environment gotchas

- Worktree isolation blocks reviewers from running `git` against the sibling. Pre-extract with
  `git archive <sha> <path> | tar -x -C <scratchpad>`; `git show` in a loop does not survive.
- The same guard rejects `bd` commands containing an apostrophe. Reword rather than escaping.
- Both projects have a package named `crack`. `regen_golden.py` already proves which one it
  imported via `crack.__file__`; keep that check in anything new that loads the sibling.
- `.beads/interactions.jsonl` is gitignored **and** tracked, so its churn blocks branch switches.
  `git stash push .beads/interactions.jsonl` before checkout. Worth fixing properly:
  `git rm --cached` it.
- The Codex reviewer could not run pytest (no writable temp/cache dir) and reviewed statically.
  Its findings were all real, but reproduce each one dynamically before acting.

## First moves

```bash
bd show coderay-q2r.5          # or q2r.6
git checkout -b port/git-history
git -C ~/code/Crack-Any-Codebase-with-AI rev-parse main   # must print 34f0ad2a70...
```

Then settle the two blockers with Mark if you are taking q2r.6, and write the plan before code.
