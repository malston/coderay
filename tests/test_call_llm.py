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

    class Usage:
        input_tokens = 0
        output_tokens = 0
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class Resp:
        def __init__(self):
            self.stop_reason = stop_reason
            self.content = [Block()]
            self.usage = Usage()

    class Messages:
        def create(self, **kwargs):
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def _fake_anthropic_module_with_usage(input_tokens, output_tokens, cache_read, cache_write, text="ok"):
    fake = types.ModuleType("anthropic")

    class Usage:
        def __init__(self):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.cache_read_input_tokens = cache_read
            self.cache_creation_input_tokens = cache_write

    class Block:
        def __init__(self):
            self.type = "text"
            self.text = text

    class Resp:
        def __init__(self):
            self.stop_reason = "end_turn"
            self.content = [Block()]
            self.usage = Usage()

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


def _fake_anthropic_module_missing_usage(text="ok"):
    fake = types.ModuleType("anthropic")
    reply_text = text

    class Block:
        type = "text"
        text = reply_text

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        usage = None

    class Messages:
        def create(self, **kwargs):
            return Resp()

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def test_anthropic_call_raises_when_usage_object_is_missing(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_missing_usage())

    with pytest.raises(RuntimeError, match="missing usage data"):
        call_llm("prompt")

    assert call_llm_module.get_usage() == []


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


def _fake_openai_module_missing_usage(text="ok"):
    fake = types.ModuleType("openai")

    class Message:
        content = text

    class Choice:
        finish_reason = "stop"
        message = Message()

    class Resp:
        choices = [Choice()]
        usage = None

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


def test_openai_call_raises_when_usage_object_is_missing(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module_missing_usage())

    with pytest.raises(RuntimeError, match="missing usage data"):
        call_llm("prompt")

    assert call_llm_module.get_usage() == []


def _install_fake_gemini_module_with_usage(monkeypatch, prompt_tokens, candidates_tokens, cached_tokens, text="ok"):
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Usage:
        def __init__(self):
            self.prompt_token_count = prompt_tokens
            self.candidates_token_count = candidates_tokens
            self.cached_content_token_count = cached_tokens

    class Candidate:
        finish_reason = "STOP"

    class Resp:
        def __init__(self):
            self.candidates = [Candidate()]
            self.text = text
            self.usage_metadata = Usage()

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
    # prompt_token_count (300) includes the cached tokens (40); input_tokens
    # must exclude them so cached tokens aren't billed at both the input and
    # cache-read rate.
    assert record["input_tokens"] == 260
    assert record["output_tokens"] == 120
    assert record["cache_read_tokens"] == 40
    assert record["cache_write_tokens"] == 0


def _install_fake_gemini_module_missing_usage(monkeypatch, text="ok"):
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Candidate:
        finish_reason = "STOP"

    class Resp:
        def __init__(self):
            self.candidates = [Candidate()]
            self.text = text
            self.usage_metadata = None

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


def test_gemini_call_raises_when_usage_object_is_missing(monkeypatch):
    call_llm_module.reset_usage()
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _install_fake_gemini_module_missing_usage(monkeypatch)

    with pytest.raises(RuntimeError, match="missing usage data"):
        call_llm("prompt")

    assert call_llm_module.get_usage() == []


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
        def __init__(self):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.cache_read_input_tokens = 0
            self.cache_creation_input_tokens = 0

    class Block:
        def __init__(self):
            self.type = "text"
            self.text = "partial"

    class Resp:
        def __init__(self):
            self.stop_reason = "max_tokens"
            self.content = [Block()]
            self.usage = Usage()

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

    class Usage:
        input_tokens = 0
        output_tokens = 0
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        usage = Usage()

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

    class Usage:
        prompt_tokens = 0
        completion_tokens = 0

    class Resp:
        choices = [Choice()]
        usage = Usage()

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

    class Usage:
        prompt_token_count = 0
        candidates_token_count = 0
        cached_content_token_count = 0

    class Resp:
        candidates = [Candidate()]
        text = reply_text
        usage_metadata = Usage()

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


def test_disk_cache_key_matches_the_marker_stripped_text_actually_sent(monkeypatch, tmp_path):
    # Every provider actually receives the marker stripped out (Anthropic as
    # a split content list, others as one string), so the on-disk cache key
    # must be derived from that same marker-stripped text -- keying on the
    # raw template text (marker included) would miss cache hits for
    # semantically identical requests.
    from coderay_utils.call_llm import CACHE_BREAKPOINT, _cache_path

    call_llm_module.CACHE_DIR = str(tmp_path)
    prompt = f"stable stuff{CACHE_BREAKPOINT}volatile stuff"
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))

    call_llm(prompt)

    expected_path = _cache_path("anthropic", "claude-sonnet-5", 16384, "stable stuffvolatile stuff")
    assert os.path.exists(expected_path)
    assert not os.path.exists(_cache_path("anthropic", "claude-sonnet-5", 16384, prompt))
