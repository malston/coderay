"""Per-model facts for the models crawl talks to: $/token pricing, and the
most input each one accepts.

Prices are $/token (not $/1M) since usage records store raw token counts.
Anthropic's cache read/write figures use the standard 0.1x/1.25x-of-input
formula documented in Anthropic's own pricing docs, not a per-model line
item. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md
for sourcing and promotional-pricing expiry dates.
"""

import json
import os
import sys

from .files import write_text_atomic

_PER_MILLION = {
    # cache_read/cache_write are 0.1x/1.25x of input ($0.20 = 2.00*0.1, $2.50 =
    # 2.00*1.25) -- if input ever changes, update these two together with it.
    ("anthropic", "claude-sonnet-5"): {
        "input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50,
    },
    ("openai", "gpt-5.6-terra"): {
        "input": 2.00, "output": 12.00, "cache_read": 0.20, "cache_write": 0.0,
    },
    # TODO(2026-12-31): promotional pricing expiry -- reverify against Google's
    # published rates after this date.
    ("gemini", "gemini-3.7-flash"): {
        "input": 0.75, "output": 3.75, "cache_read": 0.075,
        "cache_write": 0.0,  # not modeled: Gemini bills cache storage hourly, not per-token
    },
}

BUILTIN_PRICES = {
    key: {field: dollars / 1_000_000 for field, dollars in prices.items()}
    for key, prices in _PER_MILLION.items()
}

# The most input a model accepts, per model. Kept out of _PER_MILLION because
# every field in there is divided by a million to reach $/token, with no
# allowlist, so a token count placed there comes back scaled by 1e-6.
#
# A model absent from this table has no ceiling recorded and is not checked
# against one; a guessed ceiling would refuse runs that would have worked.
#
# Each figure is a limit on the input alone, not a context window spanning the
# output too. Every vendor here publishes both, and the two are easy to
# confuse: on the OpenAI page below they differ by exactly that model's output
# cap. Take the input figure, or the guard passes prompts the provider will
# refuse (coderay-8vk).
INPUT_CEILINGS = {
    # The API reported this limit itself when it refused an oversized prompt:
    # "prompt is too long: 1385407 tokens > 1000000 maximum" (coderay-cvi).
    # Anthropic's window spans the response as well, but a prompt over this on
    # its own is refused outright, so it is the input ceiling too.
    ("anthropic", "claude-sonnet-5"): 1_000_000,
    # "Maximum input tokens: 922,000", beside "1,050,000 context window" and
    # "128,000 max output tokens" --
    # developers.openai.com/api/docs/models/gpt-5.6-terra.md. Only the .md
    # form of the page carries the input row; the rendered HTML builds it
    # client-side and a fetch of that shows the window alone.
    ("openai", "gpt-5.6-terra"): 922_000,
    # "Input token limit 1,048,576", beside "Output token limit 65,536" --
    # ai.google.dev/gemini-api/docs/models/gemini-3.7-flash. Readable at run
    # time as types.Model.input_token_limit, whose own docstring reads "The
    # maximum number of input tokens that the model can handle", if this ever
    # needs checking against the live API rather than the docs.
    ("gemini", "gemini-3.7-flash"): 1_048_576,
}

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "crawl")
OVERRIDE_FILE = os.path.join(CONFIG_DIR, "pricing.json")


def _load_overrides():
    if not os.path.exists(OVERRIDE_FILE):
        return {}
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Warning: couldn't read {OVERRIDE_FILE} ({e}); ignoring overrides", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _save_override(provider, model, per_million):
    overrides = _load_overrides()
    overrides[f"{provider}:{model}"] = per_million
    os.makedirs(CONFIG_DIR, exist_ok=True)
    write_text_atomic(OVERRIDE_FILE, json.dumps(overrides, indent=2))


def get_price(provider, model):
    """$/token dict for (provider, model): the override file wins, then the
    built-in table, else None if unpriced."""
    overrides = _load_overrides()
    entry = overrides.get(f"{provider}:{model}")
    if entry is not None:
        try:
            if not isinstance(entry, dict):
                raise TypeError(f"override entry for {provider}:{model} is not an object")
            return {
                field: float(entry.get(field, 0.0) or 0.0) / 1_000_000
                for field in ("input", "output", "cache_read", "cache_write")
            }
        except (TypeError, ValueError, AttributeError) as e:
            print(f"Warning: ignoring malformed pricing override for {provider}:{model} ({e})", file=sys.stderr)
    return BUILTIN_PRICES.get((provider, model))


def input_ceiling(provider, model):
    """The most input (provider, model) accepts, or None when no figure is
    recorded for it -- an unknown ceiling means "unchecked", not "unlimited"."""
    return INPUT_CEILINGS.get((provider, model))


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


def prompt_for_pricing(provider, model):
    """Ask for $/1M pricing on an unpriced model and persist it to the
    override file. Returns the $/1M dict written, or None if skipped
    (stdin isn't a tty)."""
    if not sys.stdin.isatty():
        return None
    print(f"No pricing for {provider}/{model}. Enter $/1M tokens (blank to skip):")
    per_million = {}
    try:
        for field in ("input", "output", "cache_read", "cache_write"):
            raw = input(f"  {field.replace('_', ' ')}: ").strip()
            per_million[field] = float(raw) if raw else 0.0
    except (ValueError, EOFError):
        print("Skipping pricing entry.")
        return None
    if not any(per_million.values()):
        print("No pricing entered, skipping.")
        return None
    _save_override(provider, model, per_million)
    return per_million


def ensure_priced(provider, model):
    """Prompt for pricing if (provider, model) is unpriced and stdin is a
    tty. Call before any LLM call so a run doesn't prompt mid-flight."""
    if get_price(provider, model) is None:
        prompt_for_pricing(provider, model)
