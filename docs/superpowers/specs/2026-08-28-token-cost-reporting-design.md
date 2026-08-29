# Token cost reporting for coderay runs (coderay-ycl)

## Problem

coderay has no cost visibility. `call_llm()` (`coderay_utils/call_llm.py`) returns a plain
`str` and discards whatever token-usage data each provider's SDK response carries. Nothing
in the pipeline tracks tokens or spend, before or after a run.

## Goals

- After a real `python -m workflow path/to/repo` run, print a Claude-Code-style `Session`
  summary with real cost and token usage aggregated across every `call_llm()` call.
- `python -m workflow path/to/repo --dry-run` estimates cost _before_ spending anything,
  without calling Analyze/Relate/WriteChapters and without needing write access to the
  output dir.
- Works across Anthropic, OpenAI, and Gemini, including Anthropic's cache read/write
  pricing (see coderay-dl8, prompt caching).

## Non-goals (this iteration; see Follow-up beads)

- A per-provider real tokenizer for dry-run estimation (tiktoken, `count_tokens` endpoints).
- A per-node (SmartCrawl/Analyze/Relate/WriteChapters) cost breakdown in the summary.
- Scaling the dry-run chapter-count guess off repo size instead of a flat constant.

## Design

### Usage capture: `coderay_utils/call_llm.py`

A module-level list, reset at the start of a run:

```python
_usage_log = []

def reset_usage():
    _usage_log.clear()

def get_usage():
    return list(_usage_log)
```

`call_llm()` keeps its existing signature and `str` return type — no changes to `yaml_call`,
no changes to any node. Each invocation appends one record after the provider call (or after
a cache hit) with this shape:

```python
{
    "provider": str, "model": str,
    "input_tokens": int, "output_tokens": int,
    "cache_read_tokens": int, "cache_write_tokens": int,
    "duration_s": float, "cached": bool,
}
```

Per-provider extraction, timed around the SDK call with `time.perf_counter()`:

- **Anthropic**: `resp.usage.input_tokens`, `.output_tokens`, `.cache_read_input_tokens`,
  `.cache_creation_input_tokens`.
- **OpenAI**: `resp.usage.prompt_tokens`, `.completion_tokens`. OpenAI's chat completions
  usage doesn't expose separate cache-read/write counts the way Anthropic does; both
  cache fields are recorded as 0.
- **Gemini**: `resp.usage_metadata.prompt_token_count`, `.candidates_token_count`,
  `.cached_content_token_count` (mapped to `cache_read_tokens`; Gemini has no separate
  cache-write token count for this API, recorded as 0).

A cache hit (`_cache_get` returns non-None) appends a record with every token/duration
field at 0 and `cached=True`, then returns early — a real, correctly-zero data point,
not a skipped one.

### Pricing: `coderay_utils/pricing.py` (new file)

A dict keyed by `(provider, model)` to a `$/token` (not $/1M) record for `input`, `output`,
`cache_read`, `cache_write`. Populated only for the models coderay actually defaults to,
verified against official sources on 2026-08-28:

| Provider  | Model              | Input    | Output    | Cache read             | Cache write                                             |
| --------- | ------------------ | -------- | --------- | ---------------------- | ------------------------------------------------------- |
| Anthropic | `claude-sonnet-5`  | $2.00/1M | $10.00/1M | ~$0.20/1M (0.1x input) | ~$2.50/1M (1.25x input)                                 |
| OpenAI    | `gpt-5.6-terra`    | $2.00/1M | $12.00/1M | $0.20/1M               | n/a (0, no separate write cost)                         |
| Gemini    | `gemini-3.7-flash` | $0.75/1M | $3.75/1M  | $0.075/1M              | n/a (0; caching also bills hourly storage, not modeled) |

These are coderay's current defaults (`coderay_utils/call_llm.py`'s `_model_for()`), not the
models named in the original bead — model lineups moved since the bead was filed, and the
table tracks whatever `_model_for()` actually defaults to. Anthropic's cache read/write
figures use the standard 0.1x/1.25x-of-input formula (documented in Anthropic's own docs)
rather than a per-model line item — confirm the exact rate against the live Anthropic
pricing page before relying on this for a real invoice. OpenAI and Gemini numbers are read
directly from `developers.openai.com/api/docs/pricing` and `ai.google.dev/gemini-api/docs/pricing`
respectively. Gemini's input/output prices shown are promotional through 2026-12-31 (rising
to $1.50/$7.50 in 2027) — the pricing table should be revisited then.

A `cost_for(provider, model, usage_record)` function looks up the table; a `(provider, model)`
not in the table returns `None` (not a raised error, not a guessed number) — the summary
prints that entry's cost as `unknown` rather than a wrong number. A run using a `*_MODEL`
override to a model outside this table still gets full token counts, just no dollar figure.

#### User-editable pricing overrides

A JSON file at `$XDG_CONFIG_HOME/coderay/pricing.json` (`~/.config/coderay/pricing.json` by
default — the same `XDG_*`-with-fallback pattern `call_llm.py` already uses for `CACHE_DIR`),
keyed by `"provider:model"`, values in $/1M tokens for `input`/`output`/`cache_read`/
`cache_write`. Loaded once at startup and merged over the built-in table, with the override
file winning on a collision — this also covers correcting a stale built-in price without a
code change.

Lookup order: override file -> built-in `pricing.py` table -> `None` (unknown).

Both `main()` (actual run) and `--dry-run` resolve provider+model before any LLM call. If
that pair is in neither table and `sys.stdin.isatty()` is true, prompt once:

```text
No pricing for openai/gpt-6. Enter $/1M tokens (blank to skip):
  input:
  output:
  cache read:
  cache write:
```

Any field left blank is stored as `0`. The answers are written to the override file
immediately, so a later run (or a later call in the same run, if the same unpriced model
comes up again) doesn't re-prompt. If stdin isn't a tty (CI, scripted invocation) or the user
leaves everything blank, cost for that model stays `unknown`, exactly like today — this is
strictly additive, not a required step.

### Actual-mode summary: `workflow/__main__.py`

After `create_tour_flow().run(shared)` succeeds, `main()`:

1. Calls `reset_usage()` before the run starts (so `--out`/repeated invocations in the same
   process, e.g. tests, don't leak usage across runs).
2. Records wall-clock start/end around the `create_tour_flow().run(shared)` call.
3. Aggregates `get_usage()`: sums tokens per field, sums `cost_for(...)` where available,
   sums `duration_s` for "API duration."
4. Prints one `Session` block in the format from the bead:

   ```text
   Session
   Total cost:            $0.0000
   Total duration (API):  0s
   Total duration (wall): 8s
   Total code changes:    0 lines added, 0 lines removed
   Usage:                 0 input, 0 output, 0 cache read, 0 cache write
   ```

   "Total code changes" doesn't apply to coderay (it doesn't edit code) and is dropped from
   the printed block — the bead's example is Claude Code's own summary shown as a style
   reference, not a literal template to match line-for-line.

No per-node breakdown in this iteration (see Follow-up beads).

### Dry-run: `--dry-run` flag

A new `argparse` flag. When set, `main()` takes a separate path that never calls
`create_tour_flow()` or `call_llm`, and never creates the output directory:

1. Re-derives SmartCrawl's own preview-manifest and file-selection prompt using the same
   budget logic (`coderay_utils.list_files`, `safe_read`, `PREVIEW_CHARS_PER_FILE`) — this
   estimates the cost of the file-selection call SmartCrawl itself would make.
2. Estimates Analyze and Relate's input size from the same selected-file budget
   (`codebase_budget`), using the `identify-abstractions.md` / `analyze-relationships.md`
   prompt templates filled with that codebase text.
3. Estimates WriteChapters' cost assuming a fixed 8 chapters (the midpoint of the 5–10
   abstractions `identify-abstractions.md` asks the LLM to find), each using the
   `write-chapter.md` template filled with the same codebase text plus the current lens's
   instructions file.
4. Every prompt's input tokens are estimated as `len(text) / 4` (a chars/4 heuristic —
   documented as approximate). Output tokens are estimated as `LLM_MAX_OUTPUT_TOKENS`
   (the same cap `call_llm` reads), i.e. a worst-case upper bound, not a typical case.
5. Prints an `Estimated cost` block using the same pricing table, clearly labeled with the
   chapter-count assumption, e.g.:

   ```text
   Estimated cost (dry run)
   Assumes ~8 chapters (actual count depends on the repo)
   Estimated cost:  $0.0000 - $0.0000
   Estimated usage: ~0 input tokens, up to ~0 output tokens
   ```

No network call, no API key required, no output-dir write — satisfies the acceptance
criterion directly.

### Testing

Per repo convention, fakes go at the `call_llm` module boundary — no network, no API key:

- Fake Anthropic/OpenAI/Gemini SDK response objects (each with the right `.usage` /
  `.usage_metadata` shape) to test that `call_llm` records the correct usage fields per
  provider.
- A test that a cache hit records a zero-usage, `cached=True` entry instead of skipping.
- Tests for `pricing.cost_for`: a known `(provider, model)` computes the right cost; an
  unknown one returns `None`.
- Tests for the dry-run char-count/max-output estimate math, using a small fixture
  directory under `tests/fixtures/` (or an existing one if the repo already has a small
  sample repo for SmartCrawl tests).
- A test that `main()` with `--dry-run` doesn't create the output directory and doesn't
  import/call anything under `coderay_utils.call_llm`'s SDK branches.
- Tests for the override file: an override entry wins over a built-in one for the same
  `(provider, model)`; a non-tty stdin skips the prompt and leaves cost `unknown`; a
  tty-simulated prompt with fake input writes the expected JSON; blank fields store as `0`.

## Follow-up beads (file after this design is approved)

1. Real per-provider tokenizer for dry-run (tiktoken for OpenAI, Anthropic/Gemini
   `count_tokens` endpoints) as a more accurate opt-in mode.
2. Per-node (SmartCrawl/Analyze/Relate/WriteChapters) cost/usage breakdown in the
   actual-mode summary.
3. Research scaling the dry-run chapter-count guess off selected-file count instead of a
   flat 8.
