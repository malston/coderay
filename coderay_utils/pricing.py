"""$/token pricing for the models coderay talks to.

Values are $/token (not $/1M) since usage records store raw token counts.
Anthropic's cache read/write figures use the standard 0.1x/1.25x-of-input
formula documented in Anthropic's own pricing docs, not a per-model line
item. See docs/superpowers/specs/2026-08-28-token-cost-reporting-design.md
for sourcing and promotional-pricing expiry dates.
"""

import json
import os
import sys

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

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "coderay")
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
    with open(OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)

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
    _save_override(provider, model, per_million)
    return per_million

def ensure_priced(provider, model):
    """Prompt for pricing if (provider, model) is unpriced and stdin is a
    tty. Call before any LLM call so a run doesn't prompt mid-flight."""
    if get_price(provider, model) is None:
        prompt_for_pricing(provider, model)
