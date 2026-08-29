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


def test_override_file_wins_over_builtin_table():
    from coderay_utils.pricing import _save_override, get_price

    _save_override(
        "anthropic", "claude-sonnet-5",
        {"input": 99.0, "output": 99.0, "cache_read": 0.0, "cache_write": 0.0},
    )

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 99.0 / 1_000_000


def test_get_price_defaults_a_missing_override_field_to_zero():
    from coderay_utils.pricing import _save_override, get_price

    _save_override("anthropic", "claude-sonnet-5", {"input": 2.0})

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 2.0 / 1_000_000
    assert price["output"] == 0.0
    assert price["cache_read"] == 0.0
    assert price["cache_write"] == 0.0


def test_get_price_falls_back_to_builtin_table_on_non_numeric_override_field():
    from coderay_utils.pricing import _save_override, get_price

    _save_override("anthropic", "claude-sonnet-5", {"input": "two"})

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 2.00 / 1_000_000


def test_get_price_falls_back_to_none_on_non_numeric_override_field_for_an_unpriced_model():
    from coderay_utils.pricing import _save_override, get_price

    _save_override("openai", "gpt-6-malformed", {"input": "two"})

    assert get_price("openai", "gpt-6-malformed") is None


def test_get_price_falls_back_to_builtin_table_on_non_dict_override_entry():
    from coderay_utils.pricing import _save_override, get_price

    _save_override("anthropic", "claude-sonnet-5", [1, 2, 3])

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 2.00 / 1_000_000


def test_get_price_treats_non_dict_top_level_override_file_as_no_overrides(tmp_path):
    import coderay_utils.pricing as pricing_module
    from coderay_utils.pricing import get_price

    with open(pricing_module.OVERRIDE_FILE, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")

    price = get_price("anthropic", "claude-sonnet-5")
    assert price["input"] == 2.00 / 1_000_000
    assert get_price("openai", "gpt-6-nonexistent") is None


def test_load_overrides_warns_on_corrupt_file_and_returns_empty(capsys):
    import coderay_utils.pricing as pricing_module
    from coderay_utils.pricing import _load_overrides

    with open(pricing_module.OVERRIDE_FILE, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    assert _load_overrides() == {}
    captured = capsys.readouterr()
    assert "Warning" in captured.err
    assert pricing_module.OVERRIDE_FILE in captured.err


def test_load_overrides_does_not_warn_when_file_is_missing(capsys):
    from coderay_utils.pricing import _load_overrides

    assert _load_overrides() == {}
    captured = capsys.readouterr()
    assert captured.err == ""


def test_get_price_warns_on_malformed_override_entry(capsys):
    from coderay_utils.pricing import _save_override, get_price

    _save_override("anthropic", "claude-sonnet-5", {"input": "two"})

    get_price("anthropic", "claude-sonnet-5")
    captured = capsys.readouterr()
    assert "anthropic:claude-sonnet-5" in captured.err


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


def test_prompt_returns_none_on_non_numeric_input_without_writing_override(monkeypatch):
    from coderay_utils.pricing import get_price, prompt_for_pricing

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["1.5", "not-a-number"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert prompt_for_pricing("openai", "gpt-6-badinput") is None
    assert get_price("openai", "gpt-6-badinput") is None


def test_prompt_returns_none_on_eof(monkeypatch):
    from coderay_utils.pricing import get_price, prompt_for_pricing

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert prompt_for_pricing("openai", "gpt-6-eof") is None
    assert get_price("openai", "gpt-6-eof") is None


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
