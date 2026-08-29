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
