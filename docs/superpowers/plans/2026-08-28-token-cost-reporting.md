# Token Cost Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give coderay cost visibility: an accurate `Session` summary after a real run, and a `--dry-run` cost estimate before any money is spent.

**Architecture:** `call_llm()` gains a module-level usage accumulator (no signature change), a new `coderay_utils/pricing.py` turns usage records into dollars via a verified built-in table plus a user-editable override file, and `workflow/__main__.py` gains a `--dry-run` flag and prints the summary in both modes.

**Tech Stack:** Python 3, pytest, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md`

## Global Constraints

- No network calls and no API key required in any test — fakes go at the `call_llm` module boundary (`monkeypatch.setitem(sys.modules, "anthropic", ...)` etc.), matching `tests/test_call_llm.py`'s existing pattern.
- `call_llm()` keeps its current signature and `str` return type. Do not touch `yaml_call` or any node in `workflow/nodes.py`.
- Any pricing number that isn't already verified in the spec's table must not be invented — an unpriced `(provider, model)` returns `None`/"unknown", never a guess.
- Reuse existing budget constants (`PREVIEW_CHARS_PER_FILE`, `CODEBASE_BUDGET` in `workflow/nodes.py`) for dry-run sizing instead of introducing new ones.
- Match surrounding code style: 4-space indent, double quotes, module-level constants in `SCREAMING_SNAKE_CASE`, no unrequested comments.

---

### Task 1: Usage capture in `call_llm.py`

**Files:**

- Modify: `coderay_utils/call_llm.py`
- Modify: `coderay_utils/__init__.py`
- Test: `tests/test_call_llm.py`

**Interfaces:**

- Produces: `reset_usage() -> None`, `get_usage() -> list[dict]`, `resolve_provider_and_model() -> tuple[str, str]`, `DEFAULT_MAX_OUTPUT_TOKENS: int` (all in `coderay_utils.call_llm`, re-exported from `coderay_utils`). Each usage record is `{"provider": str, "model": str, "input_tokens": int, "output_tokens": int, "cache_read_tokens": int, "cache_write_tokens": int, "duration_s": float, "cached": bool}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_call_llm.py`, after the existing `_fake_anthropic_module` helper (around line 74):

```python
def _fake_anthropic_module_with_usage(input_tokens, output_tokens, cache_read, cache_write, text="ok"):
    fake = types.ModuleType("anthropic")

    class Usage:
        def __init__(self):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.cache_read_input_tokens = cache_read
            self.cache_creation_input_tokens = cache_write

    class Block:
        type = "text"
        text = text

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        usage = Usage()

    class Messages:
        def create(self, **kwargs):
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake

def test_anthropic_call_records_usage(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setitem(
        sys.modules, "anthropic",
        _fake_anthropic_module_with_usage(input_tokens=100, output_tokens=50, cache_read=10, cache_write=5),
    )

    call_llm("prompt")

    usage = call_llm_module.get_usage()
    assert len(usage) == 1
    record = usage[0]
    assert record["provider"] == "anthropic"
    assert record["model"] == "claude-sonnet-5"
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 50
    assert record["cache_read_tokens"] == 10
    assert record["cache_write_tokens"] == 5
    assert record["cached"] is False
    assert record["duration_s"] >= 0

def _fake_openai_module_with_usage(prompt_tokens, completion_tokens, text="ok"):
    fake = types.ModuleType("openai")

    class Usage:
        def __init__(self):
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens

    class Message:
        content = text

    class Choice:
        finish_reason = "stop"
        message = Message()

    class Resp:
        choices = [Choice()]
        usage = Usage()

    class Completions:
        def create(self, **kwargs):
            return Resp()

    class Chat:
        completions = Completions()

    class OpenAI:
        def __init__(self, *a, **kw):
            self.chat = Chat()

    fake.OpenAI = OpenAI
    return fake

def test_openai_call_records_usage_with_zero_cache_fields(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setitem(
        sys.modules, "openai",
        _fake_openai_module_with_usage(prompt_tokens=200, completion_tokens=80),
    )

    call_llm("prompt")

    record = call_llm_module.get_usage()[0]
    assert record["provider"] == "openai"
    assert record["input_tokens"] == 200
    assert record["output_tokens"] == 80
    assert record["cache_read_tokens"] == 0
    assert record["cache_write_tokens"] == 0

def _install_fake_gemini_module_with_usage(monkeypatch, prompt_tokens, candidates_tokens, cached_tokens, text="ok"):
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Usage:
        prompt_token_count = prompt_tokens
        candidates_token_count = candidates_tokens
        cached_content_token_count = cached_tokens

    class Candidate:
        finish_reason = "STOP"

    class Resp:
        candidates = [Candidate()]
        text = text
        usage_metadata = Usage()

    class Models:
        def generate_content(self, **kwargs):
            return Resp()

    class Client:
        def __init__(self, *a, **kw):
            self.models = Models()

    genai_types.GenerateContentConfig = GenerateContentConfig
    genai.types = genai_types
    genai.Client = Client
    google.genai = genai

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)

def test_gemini_call_records_cached_content_as_cache_read(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _install_fake_gemini_module_with_usage(monkeypatch, prompt_tokens=300, candidates_tokens=120, cached_tokens=40)

    call_llm("prompt")

    record = call_llm_module.get_usage()[0]
    assert record["provider"] == "gemini"
    assert record["input_tokens"] == 300
    assert record["output_tokens"] == 120
    assert record["cache_read_tokens"] == 40
    assert record["cache_write_tokens"] == 0

def test_cache_hit_records_a_zero_usage_entry(monkeypatch, tmp_path):
    call_llm_module.CACHE_DIR = str(tmp_path)
    call_llm_module.reset_usage()
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))

    call_llm("prompt")  # first call: real, populates the disk cache
    call_llm("prompt")  # second call: cache hit

    usage = call_llm_module.get_usage()
    assert len(usage) == 2
    hit_record = usage[1]
    assert hit_record["cached"] is True
    assert hit_record["input_tokens"] == 0
    assert hit_record["output_tokens"] == 0
    assert hit_record["duration_s"] == 0.0

def test_resolve_provider_and_model_matches_call_llm_defaults():
    from coderay_utils.call_llm import resolve_provider_and_model
    assert resolve_provider_and_model() == ("anthropic", "claude-sonnet-5")

def _fake_anthropic_module_truncated_with_usage(input_tokens, output_tokens):
    fake = types.ModuleType("anthropic")

    class Usage:
        input_tokens = input_tokens
        output_tokens = output_tokens
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class Block:
        type = "text"
        text = "partial"

    class Resp:
        stop_reason = "max_tokens"
        content = [Block()]
        usage = Usage()

    class Messages:
        def create(self, **kwargs):
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake

def test_truncated_response_still_records_its_usage(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setitem(
        sys.modules, "anthropic",
        _fake_anthropic_module_truncated_with_usage(input_tokens=500, output_tokens=16384),
    )

    with pytest.raises(RuntimeError, match="truncated"):
        call_llm("prompt")

    usage = call_llm_module.get_usage()
    assert len(usage) == 1
    assert usage[0]["input_tokens"] == 500
    assert usage[0]["output_tokens"] == 16384
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_call_llm.py -k "usage or resolve_provider or truncated_response_still" -v`
Expected: FAIL — `get_usage`/`reset_usage`/`resolve_provider_and_model` don't exist yet.

- [ ] **Step 3: Write the implementation**

In `coderay_utils/call_llm.py`, add `import time` to the imports (line 23-26 block) and add these module-level pieces after `CACHE_BREAKPOINT` (after line 33):

```python
DEFAULT_MAX_OUTPUT_TOKENS = 16384

_usage_log = []

def reset_usage():
    """Clear accumulated usage records. Call once before a pipeline run."""
    _usage_log.clear()

def get_usage():
    """Every usage record accumulated since the last reset_usage()."""
    return list(_usage_log)

def resolve_provider_and_model():
    """The (provider, model) pair call_llm() would use right now, without calling it."""
    provider = _pick()
    return provider, _model_for(provider)

def _record_usage(provider, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, duration_s, cached):
    _usage_log.append({
        "provider": provider, "model": model,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens,
        "duration_s": duration_s, "cached": cached,
    })
```

Replace line 104 (`max_out = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "16384"))`) with:

```python
    max_out = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
```

Replace the cache-hit block (lines 122-124):

```python
    cached = _cache_get(provider, model, max_out, plain_prompt)
    if cached is not None:
        return cached
```

with:

```python
    cached = _cache_get(provider, model, max_out, plain_prompt)
    if cached is not None:
        _record_usage(provider, model, 0, 0, 0, 0, 0.0, cached=True)
        return cached

    start = time.perf_counter()
```

Replace the Anthropic branch (lines 126-140):

```python
    if provider == "anthropic":
        from anthropic import Anthropic
        content = [
            {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": suffix},
        ] if sep else prompt
        resp = Anthropic().messages.create(
            model=model,
            max_tokens=max_out,
            messages=[{"role": "user", "content": content}],
        )
        duration_s = time.perf_counter() - start
        usage = getattr(resp, "usage", None)
        _record_usage(
            provider, model,
            getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0,
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
            duration_s, cached=False,
        )
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Anthropic response truncated (stop_reason=max_tokens)")
        text_block = next((b for b in resp.content if getattr(b, "type", None) == "text"), None)
        text = text_block.text if text_block else None
```

Replace the OpenAI branch (lines 142-155):

```python
    elif provider == "openai":
        from openai import OpenAI
        # GPT-5-class models (the default here) reject the old `max_tokens` on
        # chat.completions and require `max_completion_tokens`. Every current
        # OpenAI chat model accepts the newer name, so we always use it.
        resp = OpenAI().chat.completions.create(
            model=model,
            max_completion_tokens=max_out,
            messages=[{"role": "user", "content": plain_prompt}],
        )
        duration_s = time.perf_counter() - start
        usage = getattr(resp, "usage", None)
        _record_usage(
            provider, model,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            0, 0,
            duration_s, cached=False,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("OpenAI response truncated (finish_reason=length)")
        text = choice.message.content
```

Replace the Gemini branch (lines 157-170):

```python
    elif provider == "gemini":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=model,
            contents=plain_prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_out),
        )
        duration_s = time.perf_counter() - start
        usage = getattr(resp, "usage_metadata", None)
        _record_usage(
            provider, model,
            getattr(usage, "prompt_token_count", 0) or 0,
            getattr(usage, "candidates_token_count", 0) or 0,
            getattr(usage, "cached_content_token_count", 0) or 0,
            0,
            duration_s, cached=False,
        )
        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = str(getattr(candidate, "finish_reason", "") or "")
        if candidate is not None and finish_reason and "STOP" not in finish_reason.upper():
            raise RuntimeError(f"Gemini response incomplete (finish_reason={finish_reason})")
        text = resp.text
```

In `coderay_utils/__init__.py`, change:

```python
from .call_llm import call_llm  # noqa: F401
```

to:

```python
from .call_llm import (  # noqa: F401
    DEFAULT_MAX_OUTPUT_TOKENS,
    call_llm,
    get_usage,
    reset_usage,
    resolve_provider_and_model,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_call_llm.py -v`
Expected: PASS, all tests including the pre-existing ones (the `getattr(resp, "usage", None)` fallback means the old fakes without `.usage` keep working unchanged).

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS (56+ tests)

```bash
git add coderay_utils/call_llm.py coderay_utils/__init__.py tests/test_call_llm.py
git commit -m "Capture per-call token usage in call_llm()

Records provider, model, token counts, and duration for every call
(including cache hits as a real zero-cost entry) in a module-level
accumulator read via get_usage()/reset_usage(). call_llm()'s
signature and return type are unchanged."
```

---

### Task 2: Built-in pricing table

**Files:**

- Create: `coderay_utils/pricing.py`
- Test: `tests/test_pricing.py`

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces: `get_price(provider, model) -> dict | None` (keys `input`/`output`/`cache_read`/`cache_write`, values $/token), `cost_for(provider, model, usage_record) -> float | None` (`usage_record` has the same shape Task 1 produces).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pricing.py`:

```python
from coderay_utils.pricing import cost_for, get_price

def test_get_price_returns_dollars_per_token_for_known_model():
    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 2.00 / 1_000_000
    assert price["output"] == 10.00 / 1_000_000
    assert price["cache_read"] == 0.20 / 1_000_000
    assert price["cache_write"] == 2.50 / 1_000_000

def test_get_price_returns_none_for_unknown_model():
    assert get_price("openai", "gpt-6-nonexistent") is None

def test_cost_for_known_model_sums_all_four_fields():
    usage_record = {
        "input_tokens": 1_000_000, "output_tokens": 1_000_000,
        "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000,
    }
    cost = cost_for("anthropic", "claude-sonnet-5", usage_record)
    assert cost == 2.00 + 10.00 + 0.20 + 2.50

def test_cost_for_unknown_model_returns_none():
    usage_record = {
        "input_tokens": 100, "output_tokens": 50,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
    }
    assert cost_for("openai", "gpt-6-nonexistent", usage_record) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coderay_utils.pricing'`

- [ ] **Step 3: Write the implementation**

Create `coderay_utils/pricing.py`:

```python
"""$/token pricing for the models coderay talks to.

Values are $/token (not $/1M) since usage records store raw token counts.
Anthropic's cache read/write figures use the standard 0.1x/1.25x-of-input
formula documented in Anthropic's own pricing docs, not a per-model line
item. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md
for sourcing and promotional-pricing expiry dates.
"""

_PER_MILLION = {
    ("anthropic", "claude-sonnet-5"): {
        "input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50,
    },
    ("openai", "gpt-5.6-terra"): {
        "input": 2.00, "output": 12.00, "cache_read": 0.20, "cache_write": 0.0,
    },
    ("gemini", "gemini-3.7-flash"): {
        "input": 0.75, "output": 3.75, "cache_read": 0.075, "cache_write": 0.0,
    },
}

BUILTIN_PRICES = {
    key: {field: dollars / 1_000_000 for field, dollars in prices.items()}
    for key, prices in _PER_MILLION.items()
}

def get_price(provider, model):
    """$/token dict for (provider, model), or None if unpriced."""
    return BUILTIN_PRICES.get((provider, model))

def cost_for(provider, model, usage_record):
    """Dollar cost of one usage record, or None if the model isn't priced."""
    price = get_price(provider, model)
    if price is None:
        return None
    return (
        usage_record["input_tokens"] * price["input"]
        + usage_record["output_tokens"] * price["output"]
        + usage_record["cache_read_tokens"] * price["cache_read"]
        + usage_record["cache_write_tokens"] * price["cache_write"]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coderay_utils/pricing.py tests/test_pricing.py
git commit -m "Add verified built-in pricing table

cost_for() turns a usage record into a dollar amount for the three
models coderay defaults to; an unpriced (provider, model) returns
None rather than a guess."
```

---

### Task 3: User-editable pricing overrides

**Files:**

- Modify: `coderay_utils/pricing.py`
- Modify: `coderay_utils/__init__.py`
- Test: `tests/test_pricing.py`

**Interfaces:**

- Consumes: `BUILTIN_PRICES` from Task 2.
- Produces: `ensure_priced(provider, model) -> None`, `prompt_for_pricing(provider, model) -> dict | None`. `get_price()`'s behavior changes (override file now consulted first) but its signature and success-case return shape are unchanged from Task 2.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pricing.py`:

```python
import pytest

@pytest.fixture(autouse=True)
def isolated_pricing_config(tmp_path, monkeypatch):
    import coderay_utils.pricing as pricing_module
    monkeypatch.setattr(pricing_module, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pricing_module, "OVERRIDE_FILE", str(tmp_path / "pricing.json"))
    yield

def test_override_file_wins_over_builtin_table():
    from coderay_utils.pricing import _save_override, get_price

    _save_override(
        "anthropic", "claude-sonnet-5",
        {"input": 99.0, "output": 99.0, "cache_read": 0.0, "cache_write": 0.0},
    )

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 99.0 / 1_000_000

def test_prompt_skips_on_non_tty_stdin(monkeypatch):
    from coderay_utils.pricing import prompt_for_pricing

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert prompt_for_pricing("openai", "gpt-6-new") is None

def test_prompt_writes_entered_values_to_override_file(monkeypatch):
    from coderay_utils.pricing import get_price, prompt_for_pricing

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["1.5", "9.0", "0.1", "0.0"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    prompt_for_pricing("openai", "gpt-6-new")

    price = get_price("openai", "gpt-6-new")
    assert price["input"] == 1.5 / 1_000_000
    assert price["output"] == 9.0 / 1_000_000
    assert price["cache_read"] == 0.1 / 1_000_000
    assert price["cache_write"] == 0.0

def test_prompt_stores_blank_fields_as_zero(monkeypatch):
    from coderay_utils.pricing import get_price, prompt_for_pricing

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    prompt_for_pricing("openai", "gpt-6-blank")

    assert get_price("openai", "gpt-6-blank") == {
        "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0,
    }

def test_ensure_priced_does_not_prompt_for_a_known_model(monkeypatch):
    from coderay_utils.pricing import ensure_priced

    def fail_if_called(prompt):
        raise AssertionError("should not prompt for a priced model")

    monkeypatch.setattr("builtins.input", fail_if_called)
    ensure_priced("anthropic", "claude-sonnet-5")  # no exception

def test_ensure_priced_prompts_for_an_unknown_model_on_a_tty(monkeypatch):
    from coderay_utils.pricing import ensure_priced, get_price

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["1.0", "2.0", "0.0", "0.0"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    ensure_priced("openai", "gpt-6-ensure")

    assert get_price("openai", "gpt-6-ensure") is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: FAIL — `_save_override`, `prompt_for_pricing`, `ensure_priced`, `CONFIG_DIR`, `OVERRIDE_FILE` don't exist yet.

- [ ] **Step 3: Write the implementation**

In `coderay_utils/pricing.py`, add these imports at the top of the file:

```python
import json
import os
import sys
```

Add after `BUILTIN_PRICES` and before the existing `get_price`:

```python
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "coderay")
OVERRIDE_FILE = os.path.join(CONFIG_DIR, "pricing.json")

def _load_overrides():
    if not os.path.exists(OVERRIDE_FILE):
        return {}
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _save_override(provider, model, per_million):
    overrides = _load_overrides()
    overrides[f"{provider}:{model}"] = per_million
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)
```

Replace the existing `get_price` function with:

```python
def get_price(provider, model):
    """$/token dict for (provider, model): the override file wins, then the
    built-in table, else None if unpriced."""
    overrides = _load_overrides()
    entry = overrides.get(f"{provider}:{model}")
    if entry is not None:
        return {field: dollars / 1_000_000 for field, dollars in entry.items()}
    return BUILTIN_PRICES.get((provider, model))
```

Add after `cost_for`:

```python
def prompt_for_pricing(provider, model):
    """Ask for $/1M pricing on an unpriced model and persist it to the
    override file. Returns the $/1M dict written, or None if skipped
    (stdin isn't a tty)."""
    if not sys.stdin.isatty():
        return None
    print(f"No pricing for {provider}/{model}. Enter $/1M tokens (blank to skip):")
    per_million = {}
    for field in ("input", "output", "cache_read", "cache_write"):
        raw = input(f"  {field.replace('_', ' ')}: ").strip()
        per_million[field] = float(raw) if raw else 0.0
    _save_override(provider, model, per_million)
    return per_million

def ensure_priced(provider, model):
    """Prompt for pricing if (provider, model) is unpriced and stdin is a
    tty. Call before any LLM call so a run doesn't prompt mid-flight."""
    if get_price(provider, model) is None:
        prompt_for_pricing(provider, model)
```

In `coderay_utils/__init__.py`, add after the `call_llm` import block:

```python
from .pricing import (  # noqa: F401
    cost_for,
    ensure_priced,
    get_price,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS

```bash
git add coderay_utils/pricing.py coderay_utils/__init__.py tests/test_pricing.py
git commit -m "Add user-editable pricing overrides

An unpriced (provider, model) prompts once (only on a tty) for
$/1M pricing and persists it to ~/.config/coderay/pricing.json,
which wins over the built-in table on every later lookup."
```

---

### Task 4: Actual-mode `Session` summary

**Files:**

- Modify: `workflow/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**

- Consumes: `get_usage`, `reset_usage`, `resolve_provider_and_model` (Task 1), `cost_for`, `ensure_priced` (Tasks 2-3).
- Produces: `format_session_summary(usage_records, wall_seconds) -> str`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main.py`, and add `format_session_summary` to the existing `from workflow.__main__ import (...)` block:

```python
def test_format_session_summary_reports_unknown_cost_for_an_unpriced_model():
    usage = [{
        "provider": "openai", "model": "gpt-6-mystery",
        "input_tokens": 100, "output_tokens": 50,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "duration_s": 1.5, "cached": False,
    }]
    out = format_session_summary(usage, wall_seconds=8.0)
    assert "Session" in out
    assert "Total cost:            unknown" in out
    assert "Total duration (API):  2s" in out
    assert "Total duration (wall): 8s" in out
    assert "Usage:                 100 input, 50 output, 0 cache read, 0 cache write" in out

def test_format_session_summary_sums_cost_across_records_for_a_priced_model():
    usage = [
        {
            "provider": "anthropic", "model": "claude-sonnet-5",
            "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "duration_s": 1.0, "cached": False,
        },
        {
            "provider": "anthropic", "model": "claude-sonnet-5",
            "input_tokens": 0, "output_tokens": 1_000_000,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "duration_s": 2.0, "cached": False,
        },
    ]
    out = format_session_summary(usage, wall_seconds=5.0)
    assert "Total cost:            $12.0000" in out
    assert "Total duration (API):  3s" in out

def test_format_session_summary_handles_empty_usage():
    out = format_session_summary([], wall_seconds=0.4)
    assert "Total cost:            $0.0000" in out
    assert "Usage:                 0 input, 0 output, 0 cache read, 0 cache write" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -k format_session_summary -v`
Expected: FAIL with `ImportError: cannot import name 'format_session_summary'`

- [ ] **Step 3: Write the implementation**

In `workflow/__main__.py`, add to the import block near the top (after the existing `from workflow.nodes import ...` line):

```python
import time

from coderay_utils import cost_for, ensure_priced, get_usage, reset_usage, resolve_provider_and_model
```

Add this function anywhere after the other `write_*`/`build_*` helpers (e.g. right before `dump_run_state`):

```python
def format_session_summary(usage_records, wall_seconds):
    """Render the actual-run Session summary from call_llm.get_usage() records
    and total wall-clock seconds. Cost prints as 'unknown' if any record's
    (provider, model) has no pricing entry."""
    total_input = sum(r["input_tokens"] for r in usage_records)
    total_output = sum(r["output_tokens"] for r in usage_records)
    total_cache_read = sum(r["cache_read_tokens"] for r in usage_records)
    total_cache_write = sum(r["cache_write_tokens"] for r in usage_records)
    total_api_duration = sum(r["duration_s"] for r in usage_records)

    costs = [cost_for(r["provider"], r["model"], r) for r in usage_records]
    cost_line = "unknown" if any(c is None for c in costs) else f"${sum(costs):.4f}"

    return (
        "Session\n"
        f"Total cost:            {cost_line}\n"
        f"Total duration (API):  {total_api_duration:.0f}s\n"
        f"Total duration (wall): {wall_seconds:.0f}s\n"
        f"Usage:                 {total_input} input, {total_output} output, "
        f"{total_cache_read} cache read, {total_cache_write} cache write"
    )
```

Now wire it into `main()`. Replace the current `main()` body from `args = ap.parse_args()` through the end of the function with:

```python
    args = ap.parse_args()

    if not os.path.isdir(args.repo_path):
        ap.error(f"{args.repo_path} is not a directory")

    provider, model = resolve_provider_and_model()
    ensure_priced(provider, model)

    name = os.path.basename(os.path.abspath(args.repo_path))
    out = args.out or default_output_dir(args.repo_path, args.instructions)
    os.makedirs(out, exist_ok=True)

    reset_usage()
    wall_start = time.perf_counter()

    shared: PipelineState = {"repo_path": args.repo_path, "instructions": args.instructions}
    try:
        create_tour_flow().run(shared)
    except Exception:
        state_path = dump_run_state(shared, out)
        print(f"\nPipeline failed. Wrote partial run state to {state_path}")
        raise

    wall_seconds = time.perf_counter() - wall_start

    chapters = shared["chapters"]
    mermaid = build_mermaid(shared["abstractions"], shared["relationships"])

    write_chapter_files(chapters, name, out, shared["relationships"])
    write_index_md(chapters, name, args.instructions, shared["summary"], mermaid, out)
    write_index_html(
        chapters, name, args.instructions, shared["summary"], mermaid,
        shared["selected_files"], shared["selection_reasoning"], out,
    )

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")
    print()
    print(format_session_summary(get_usage(), wall_seconds))
```

(Task 5 will insert a `--dry-run` branch between `ensure_priced(...)` and `name = os.path.basename(...)`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS

```bash
git add workflow/__main__.py tests/test_main.py
git commit -m "Print a Session cost/usage summary after a real run

Aggregates call_llm's usage records into one Claude-Code-style
Session block. Cost prints as 'unknown' rather than a wrong number
whenever any call used an unpriced model."
```

---

### Task 5: `--dry-run` cost estimate

**Files:**

- Modify: `workflow/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**

- Consumes: `cost_for` (Task 2), `resolve_provider_and_model`/`ensure_priced` already wired into `main()` (Task 4), `CODEBASE_BUDGET`/`PROMPTS_DIR`/`SmartCrawl`/`load_instructions` from `workflow.nodes`, `fill`/`list_files`/`safe_read`/`read_prompt` from `coderay_utils`.
- Produces: `estimate_dry_run_cost(repo_path, instructions, provider, model, chapter_guess=8) -> dict`, `format_dry_run_summary(estimate) -> str`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main.py`, and add `estimate_dry_run_cost`, `format_dry_run_summary` to the `from workflow.__main__ import (...)` block:

```python
def _make_repo_files(tmp_path, count, size=500):
    for i in range(count):
        (tmp_path / f"file_{i}.py").write_text("x" * size, encoding="utf-8")

def test_estimate_dry_run_cost_returns_a_cost_range_for_a_priced_model(tmp_path):
    _make_repo_files(tmp_path, count=5)

    estimate = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "anthropic", "claude-sonnet-5")

    assert estimate["chapter_guess"] == 8
    assert estimate["estimated_input_tokens"] > 0
    assert estimate["estimated_output_tokens_worst_case"] > 0
    assert estimate["cost_low"] is not None
    assert estimate["cost_high"] is not None
    assert estimate["cost_low"] <= estimate["cost_high"]

def test_estimate_dry_run_cost_is_unpriced_for_an_unknown_model(tmp_path):
    _make_repo_files(tmp_path, count=3)

    estimate = estimate_dry_run_cost(str(tmp_path), "beginner-tutorial", "openai", "gpt-6-mystery")

    assert estimate["cost_low"] is None
    assert estimate["cost_high"] is None

def test_format_dry_run_summary_shows_the_chapter_assumption_and_cost_range():
    estimate = {
        "provider": "anthropic", "model": "claude-sonnet-5", "chapter_guess": 8,
        "estimated_input_tokens": 1000, "estimated_output_tokens_worst_case": 5000,
        "cost_low": 0.01, "cost_high": 0.05,
    }
    out = format_dry_run_summary(estimate)
    assert "Estimated cost (dry run)" in out
    assert "Assumes ~8 chapters" in out
    assert "$0.0100 - $0.0500" in out
    assert "~1000 input tokens" in out
    assert "~5000 output tokens" in out

def test_format_dry_run_summary_shows_unknown_for_an_unpriced_model():
    estimate = {
        "provider": "openai", "model": "gpt-6-mystery", "chapter_guess": 8,
        "estimated_input_tokens": 1000, "estimated_output_tokens_worst_case": 5000,
        "cost_low": None, "cost_high": None,
    }
    out = format_dry_run_summary(estimate)
    assert "unknown" in out

def test_dry_run_flag_estimates_without_creating_the_output_directory(tmp_path, monkeypatch):
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    env = dict(os.environ, ANTHROPIC_API_KEY="test-key", XDG_CONFIG_HOME=str(tmp_path / "config"))
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        env.pop(var, None)

    result = subprocess.run(
        [sys.executable, "-m", "workflow", str(repo), "--dry-run", "--out", str(out_dir)],
        capture_output=True, text=True, env=env, check=True,
    )

    assert "Estimated cost (dry run)" in result.stdout
    assert not out_dir.exists()
```

`os` is already imported in `tests/test_main.py`? Check — if not, add `import os` next to the existing `import json`/`import subprocess`/`import sys` block at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -k "dry_run or estimate" -v`
Expected: FAIL — `estimate_dry_run_cost`/`format_dry_run_summary` don't exist, and `--dry-run` isn't a recognized flag yet.

- [ ] **Step 3: Write the implementation**

In `workflow/__main__.py`, extend the `from workflow.nodes import ...` line to:

```python
from workflow.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    SmartCrawl,
    load_instructions,
)
```

Add to the `coderay_utils` import line so it reads:

```python
from coderay_utils import (
    cost_for, ensure_priced, fill, get_usage, list_files,
    read_prompt, reset_usage, resolve_provider_and_model, safe_read,
)
```

(`fill`, `list_files`, `read_prompt`, `safe_read` are already re-exported by `coderay_utils/__init__.py` today — only `cost_for`, `ensure_priced`, `get_usage`, `reset_usage`, `resolve_provider_and_model` are new to this file.)

Add these two functions and one constant, right after `format_session_summary`:

```python
DRY_RUN_CHAPTER_GUESS = 8

def _codebase_preview_text(repo_path, budget):
    """Best-guess codebase text for dry-run sizing: the first files
    list_files() returns, up to budget chars. Not the same files the real
    SmartCrawl LLM call would pick, but close enough in total size to
    estimate prompt length."""
    parts = []
    total = 0
    for p in list_files(repo_path):
        if total >= budget:
            break
        text = safe_read(p)
        if text is None:
            continue
        parts.append(text)
        total += len(text)
    return "\n\n".join(parts)

def estimate_dry_run_cost(repo_path, instructions, provider, model, chapter_guess=DRY_RUN_CHAPTER_GUESS):
    """Estimate the cost of a real run without calling any LLM. Input tokens
    use a chars/4 heuristic; output tokens assume every call hits the
    configured max-output cap (a worst-case upper bound, not a typical case)."""
    from coderay_utils.call_llm import DEFAULT_MAX_OUTPUT_TOKENS
    max_out = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))

    # Reuses SmartCrawl's own prep() for the file-selection prompt instead of
    # rebuilding its preview-manifest logic here -- one source of truth for
    # what that prompt looks like.
    select_prompt, _files, _root = SmartCrawl().prep({"repo_path": repo_path})

    codebase = _codebase_preview_text(repo_path, CODEBASE_BUDGET)
    analyze_prompt = fill(read_prompt(PROMPTS_DIR, "identify-abstractions.md"), codebase=codebase)
    relate_prompt = fill(
        read_prompt(PROMPTS_DIR, "analyze-relationships.md"),
        abstractions="(estimated -- not yet known)", codebase=codebase,
    )
    chapter_prompt = fill(
        read_prompt(PROMPTS_DIR, "write-chapter.md"),
        name="(estimated)", description="(estimated)", chapter_num=1, total=chapter_guess,
        prev_chapters="(estimated)", chapter_list="(estimated)", codebase=codebase,
        instructions=load_instructions(instructions),
    )

    prompts = [select_prompt, analyze_prompt, relate_prompt] + [chapter_prompt] * chapter_guess
    estimated_input_tokens = sum(len(p) // 4 for p in prompts)
    estimated_output_tokens_worst_case = max_out * len(prompts)

    low_usage = {"input_tokens": estimated_input_tokens, "output_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_tokens": 0}
    high_usage = {"input_tokens": estimated_input_tokens, "output_tokens": estimated_output_tokens_worst_case,
                  "cache_read_tokens": 0, "cache_write_tokens": 0}

    return {
        "provider": provider, "model": model, "chapter_guess": chapter_guess,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens_worst_case": estimated_output_tokens_worst_case,
        "cost_low": cost_for(provider, model, low_usage),
        "cost_high": cost_for(provider, model, high_usage),
    }

def format_dry_run_summary(estimate):
    if estimate["cost_low"] is None or estimate["cost_high"] is None:
        cost_line = "unknown (no pricing for this model)"
    else:
        cost_line = f"${estimate['cost_low']:.4f} - ${estimate['cost_high']:.4f}"
    return (
        "Estimated cost (dry run)\n"
        f"Assumes ~{estimate['chapter_guess']} chapters (actual count depends on the repo)\n"
        f"Estimated cost:  {cost_line}\n"
        f"Estimated usage: ~{estimate['estimated_input_tokens']} input tokens, "
        f"up to ~{estimate['estimated_output_tokens_worst_case']} output tokens"
    )
```

Add the flag to the `argparse` setup in `main()`:

```python
    ap.add_argument("--dry-run", action="store_true")
```

(right after the existing `ap.add_argument("--instructions", ...)` line).

Insert the dry-run branch into `main()`, right after `ensure_priced(provider, model)` and before `name = os.path.basename(...)`:

```python
    if args.dry_run:
        print(format_dry_run_summary(estimate_dry_run_cost(args.repo_path, args.instructions, provider, model)))
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS

```bash
git add workflow/__main__.py tests/test_main.py
git commit -m "Add --dry-run cost estimate

Estimates cost from SmartCrawl's preview manifest and the prompt
templates, assuming a fixed ~8-chapter WriteChapters run, without
calling any LLM, creating the output directory, or requiring
network access."
```

---

### Task 6: File follow-up beads

Not a code task — no tests, no commit (bead creation isn't tracked in git).

- [ ] **Step 1: File the three follow-up items from the spec**

```bash
bd create --title="Real per-provider tokenizer for coderay --dry-run" \
  --description="Replace the chars/4 heuristic with tiktoken (OpenAI) and the Anthropic/Gemini count_tokens endpoints as a more accurate opt-in mode. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md Non-goals." \
  --type=task --priority=3

bd create --title="Per-node cost/usage breakdown in coderay's Session summary" \
  --description="Break format_session_summary's aggregate down by SmartCrawl/Analyze/Relate/WriteChapters instead of one total. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md Non-goals." \
  --type=task --priority=3

bd create --title="Scale coderay dry-run's chapter-count guess off repo size" \
  --description="estimate_dry_run_cost() assumes a flat 8 chapters. Research whether selected-file count predicts abstraction count well enough to replace the constant. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md Non-goals." \
  --type=task --priority=4
```

- [ ] **Step 2: Report the created bead IDs to Mark**

No commit for this task.

---

## Self-Review Notes

- **Spec coverage:** Usage capture (Task 1) → Pricing table (Task 2) → Override file/prompt (Task 3) → actual-mode summary (Task 4) → `--dry-run` (Task 5) → Follow-up beads (Task 6). Every section of the spec maps to a task.
- **Type consistency:** the usage-record shape from Task 1 (`input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_write_tokens`/`duration_s`/`cached`/`provider`/`model`) is used unchanged by `cost_for` (Task 2/3) and `format_session_summary` (Task 4). The pricing dict shape (`input`/`output`/`cache_read`/`cache_write`) is used unchanged by `get_price`, `cost_for`, `prompt_for_pricing`'s stored JSON, and `_save_override`.
- **Placeholder scan:** none — every step has literal code. Task 1's Step 1 intentionally shows and then discards a messy first draft of the truncation test (calling that out explicitly, not leaving a TBD) because a class-patching approach was worth ruling out before landing on the clean dedicated-fake version.
