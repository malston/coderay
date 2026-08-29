import importlib
import json
import os
import stat
import sys
import types

import pytest

# coderay_utils/__init__.py re-exports call_llm the function under the same name as the
# call_llm module, shadowing `coderay_utils.call_llm` as an attribute -- fetch the
# actual module out of sys.modules instead of relying on attribute access.
call_llm_module = importlib.import_module("coderay_utils.call_llm")
from coderay_utils.call_llm import _cache_path, _cache_put, call_llm


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


def test_cache_dir_is_not_world_or_group_readable(tmp_path):
    # Cached responses can contain target-repo file contents/secrets (coderay-3fk),
    # so the cache dir must not be readable by other users on the machine.
    cache_dir = tmp_path / "coderay-cache"
    call_llm_module.CACHE_DIR = str(cache_dir)
    _cache_put("anthropic", "claude-x", 100, "hello", "world")
    mode = os.stat(cache_dir).st_mode
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


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


def _fake_anthropic_module_capturing_kwargs(captured, text="ok"):
    fake = types.ModuleType("anthropic")
    reply_text = text

    class Block:
        type = "text"
        text = reply_text

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def test_prompt_with_cache_breakpoint_sends_a_cached_prefix_block(monkeypatch):
    from coderay_utils.call_llm import CACHE_BREAKPOINT

    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_capturing_kwargs(captured))

    call_llm(f"stable stuff{CACHE_BREAKPOINT}volatile stuff")

    content = captured["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "stable stuff", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "volatile stuff"},
    ]


def test_prompt_without_cache_breakpoint_sends_a_plain_string(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_capturing_kwargs(captured))

    call_llm("no breakpoint here")

    assert captured["messages"][0]["content"] == "no breakpoint here"


def test_breakpoint_lookalike_in_untrusted_content_does_not_fool_the_split(monkeypatch):
    # The codebase block is untrusted repo content and sits before the real
    # breakpoint in write-chapter.md. A target repo containing the literal
    # marker string must not be treated as the real split point -- the real
    # breakpoint is always the last occurrence in a correctly-filled prompt.
    from coderay_utils.call_llm import CACHE_BREAKPOINT

    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_capturing_kwargs(captured))

    prompt = f"stable stuff{CACHE_BREAKPOINT}fake in untrusted content{CACHE_BREAKPOINT}real volatile stuff"
    call_llm(prompt)

    content = captured["messages"][0]["content"]
    assert content == [
        {
            "type": "text",
            "text": f"stable stuff{CACHE_BREAKPOINT}fake in untrusted content",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "real volatile stuff"},
    ]


def test_marker_with_empty_prefix_or_suffix_is_ignored_as_a_split_point(monkeypatch):
    # A marker echoed into LLM-generated prev_chapters text (untrusted-repo-
    # derived) could land right at the start or end of the prompt, producing
    # an empty prefix or suffix. Splitting there would either send an empty
    # content block to Anthropic or cache nothing useful -- both are worse
    # than treating the prompt as unsplit.
    from coderay_utils.call_llm import CACHE_BREAKPOINT

    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_capturing_kwargs(captured))
    call_llm(f"{CACHE_BREAKPOINT}everything after")
    assert captured["messages"][0]["content"] == f"{CACHE_BREAKPOINT}everything after"

    captured.clear()
    call_llm(f"everything before{CACHE_BREAKPOINT}")
    assert captured["messages"][0]["content"] == f"everything before{CACHE_BREAKPOINT}"


def _fake_openai_module_capturing_kwargs(captured, text="ok"):
    fake = types.ModuleType("openai")

    class Message:
        content = text

    class Choice:
        finish_reason = "stop"
        message = Message()

    class Resp:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Resp()

    class Chat:
        completions = Completions()

    class OpenAI:
        def __init__(self, *a, **kw):
            self.chat = Chat()

    fake.OpenAI = OpenAI
    return fake


def test_cache_breakpoint_marker_is_stripped_for_non_anthropic_providers(monkeypatch):
    from coderay_utils.call_llm import CACHE_BREAKPOINT

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module_capturing_kwargs(captured))

    call_llm(f"stable stuff{CACHE_BREAKPOINT}volatile stuff")

    sent_prompt = captured["messages"][0]["content"]
    assert CACHE_BREAKPOINT not in sent_prompt
    assert sent_prompt == "stable stuffvolatile stuff"


def _install_fake_gemini_module(monkeypatch, captured, text="ok"):
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    reply_text = text

    class Candidate:
        finish_reason = "STOP"

    class Resp:
        candidates = [Candidate()]
        text = reply_text

    class Models:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
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


def test_cache_breakpoint_marker_is_stripped_for_gemini(monkeypatch):
    from coderay_utils.call_llm import CACHE_BREAKPOINT

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}
    _install_fake_gemini_module(monkeypatch, captured)

    call_llm(f"stable stuff{CACHE_BREAKPOINT}volatile stuff")

    assert CACHE_BREAKPOINT not in captured["contents"]
    assert captured["contents"] == "stable stuffvolatile stuff"


def test_disk_cache_key_is_unaffected_by_the_cache_breakpoint_split(monkeypatch, tmp_path):
    # The disk cache (separate from Anthropic's own prompt cache) must key off
    # the full, unsplit prompt -- hashing prefix/suffix separately would
    # change the on-disk cache key and silently break hit rates.
    from coderay_utils.call_llm import CACHE_BREAKPOINT, _cache_path

    call_llm_module.CACHE_DIR = str(tmp_path)
    prompt = f"stable stuff{CACHE_BREAKPOINT}volatile stuff"
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))

    call_llm(prompt)

    expected_path = _cache_path("anthropic", "claude-sonnet-4-6", 16384, prompt)
    assert os.path.exists(expected_path)
