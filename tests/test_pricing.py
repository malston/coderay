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
