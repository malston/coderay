import importlib
import json
import sys
import types

import pytest

# utils/__init__.py re-exports call_llm the function under the same name as the
# call_llm module, shadowing `utils.call_llm` as an attribute -- fetch the
# actual module out of sys.modules instead of relying on attribute access.
call_llm_module = importlib.import_module("utils.call_llm")
from utils.call_llm import _cache_path, _cache_put, call_llm


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(call_llm_module, "CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


def test_cache_key_changes_with_max_output_tokens():
    a = _cache_path("anthropic", "claude-x", 100, "hello")
    b = _cache_path("anthropic", "claude-x", 200, "hello")
    assert a != b


def test_cache_put_leaves_no_temp_files_behind(tmp_path):
    call_llm_module.CACHE_DIR = str(tmp_path)
    _cache_put("anthropic", "claude-x", 100, "hello", "world")
    entries = list(tmp_path.iterdir())
    assert len(entries) == 1
    assert json.loads(entries[0].read_text())["response"] == "world"


def _fake_anthropic_module(stop_reason, text="hi", block_type="text"):
    fake = types.ModuleType("anthropic")

    class Block:
        def __init__(self):
            self.type = block_type
            self.text = text

    class Resp:
        def __init__(self):
            self.stop_reason = stop_reason
            self.content = [Block()]

    class Messages:
        def create(self, **kwargs):
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def test_truncated_anthropic_response_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("max_tokens"))
    with pytest.raises(RuntimeError, match="truncated"):
        call_llm("prompt")


def test_thinking_only_anthropic_response_raises(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "anthropic", _fake_anthropic_module("end_turn", block_type="thinking")
    )
    with pytest.raises(RuntimeError, match="empty response"):
        call_llm("prompt")


def test_healthy_anthropic_response_is_cached_and_returned(monkeypatch, tmp_path):
    call_llm_module.CACHE_DIR = str(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))
    assert call_llm("prompt") == "ok"
    assert list(tmp_path.iterdir())


def test_unknown_provider_raises_a_helpful_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "carrier-pigeon")
    with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER='carrier-pigeon'"):
        call_llm("prompt")


def test_provider_env_var_is_stripped_and_lowercased(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  ANTHROPIC  ")
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))
    assert call_llm("prompt") == "ok"
