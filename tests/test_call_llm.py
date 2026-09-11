import importlib
import json
import os
import stat
import sys
import types

import pytest

# crawl.core/__init__.py re-exports call_llm the function under the same name as the
# call_llm module, shadowing `crawl.core.call_llm` as an attribute -- fetch the
# actual module out of sys.modules instead of relying on attribute access.
call_llm_module = importlib.import_module("crawl.core.call_llm")
from crawl.core.call_llm import _cache_path, _cache_put, call_llm


class _FakeStream:
    """Mimics the context manager `Anthropic().messages.stream(...)` returns."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._resp


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(call_llm_module, "CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # A developer's shell may export this for interactive `crawl` runs; a
    # test that hardcodes DEFAULT_MAX_OUTPUT_TOKENS in an expected cache path
    # must not inherit that value, or it computes a different key than what
    # call_llm() actually wrote (coderay-d8q). Tests that need a specific
    # value still set it themselves via monkeypatch.setenv.
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    # Same reason as the cap above: .env.example ships these blank, so a
    # developer's shell may export one, and a test asserting the default model
    # or building a cache key from it then works against a different value.
    for var in ("ANTHROPIC_MODEL", "OPENAI_MODEL", "GEMINI_MODEL"):
        monkeypatch.delenv(var, raising=False)
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
        def stream(self, **kwargs):
            return _FakeStream(Resp())

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
        def stream(self, **kwargs):
            return _FakeStream(Resp())

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
        def stream(self, **kwargs):
            return _FakeStream(Resp())

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
    from crawl.core.call_llm import resolve_provider_and_model
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
        def stream(self, **kwargs):
            return _FakeStream(Resp())

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
        def stream(self, **kwargs):
            captured.update(kwargs)
            return _FakeStream(Resp())

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def test_prompt_with_cache_breakpoint_sends_a_cached_prefix_block(monkeypatch):
    from crawl.core.call_llm import CACHE_BREAKPOINT

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
    from crawl.core.call_llm import CACHE_BREAKPOINT

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
    from crawl.core.call_llm import CACHE_BREAKPOINT

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
    from crawl.core.call_llm import CACHE_BREAKPOINT

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
    from crawl.core.call_llm import CACHE_BREAKPOINT

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
    from crawl.core.call_llm import CACHE_BREAKPOINT, _cache_path

    call_llm_module.CACHE_DIR = str(tmp_path)
    prompt = f"stable stuff{CACHE_BREAKPOINT}volatile stuff"
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("end_turn", text="ok"))

    call_llm(prompt)

    expected_path = _cache_path("anthropic", "claude-sonnet-5", 16384, "stable stuffvolatile stuff")
    assert os.path.exists(expected_path)
    assert not os.path.exists(_cache_path("anthropic", "claude-sonnet-5", 16384, prompt))


def _fake_anthropic_module_stream_only(input_tokens, output_tokens, cache_read, cache_write, text="ok"):
    # `create` is present but poisoned. A regression to the non-streaming call
    # then fails with a message naming the cause, rather than with an incidental
    # AttributeError from a method that merely happened to be absent. The real
    # SDK exposes both methods, so the fake should too.
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
        def stream(self, **kwargs):
            return _FakeStream(Resp())

        def create(self, **kwargs):
            raise AssertionError(
                "call_llm used the non-streaming messages.create(). The anthropic "
                "path must stream: a max_tokens above 21333 makes the SDK raise "
                "before the request is sent. See bead coderay-q2r.9.")

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.Anthropic = Anthropic
    return fake


def test_anthropic_call_uses_streaming_not_create(monkeypatch):
    # coderay backend analysis sets LLM_MAX_OUTPUT_TOKENS=32768, which the
    # SDK's non-streaming path rejects outright (ValueError: "Streaming is
    # required for operations that may take longer than 10 minutes."). A
    # The fake's `create` is poisoned, so a call_llm() that regresses to
    # `messages.create(...)` fails with a message naming the cause.
    call_llm_module.reset_usage()
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "32768")
    monkeypatch.setitem(
        sys.modules, "anthropic",
        _fake_anthropic_module_stream_only(input_tokens=100, output_tokens=50, cache_read=10, cache_write=5),
    )

    result = call_llm("prompt")

    assert result == "ok"
    record = call_llm_module.get_usage()[0]
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 50
    assert record["cache_read_tokens"] == 10
    assert record["cache_write_tokens"] == 5


def test_truncated_response_is_its_own_error_and_says_how_to_raise_the_cap(monkeypatch):
    """coderay-q2r.46. A truncation is deterministic (same prompt, same cap,
    same cut), so callers need to tell it from a transient failure, and the
    user needs to know which knob to turn."""
    from crawl.core.call_llm import ResponseTruncated
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("max_tokens"))
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "16384")
    with pytest.raises(ResponseTruncated, match=r"LLM_MAX_OUTPUT_TOKENS.*16384"):
        call_llm("prompt")


# coderay-5wu.21: .env.example ships LLM_MAX_OUTPUT_TOKENS blank, and sourcing
# the template exports the empty string.
def test_a_blank_max_output_tokens_means_unset(monkeypatch):
    from crawl.core.call_llm import DEFAULT_MAX_OUTPUT_TOKENS, max_output_tokens
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "")
    assert max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS


@pytest.mark.parametrize("bad", ["lots", "1.5", "0", "-3"])
def test_a_bad_max_output_tokens_names_the_variable_and_stops_before_any_call(monkeypatch, bad):
    from crawl.core.call_llm import max_output_tokens
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", bad)
    with pytest.raises(SystemExit, match=f"LLM_MAX_OUTPUT_TOKENS.*{bad!r}"):
        max_output_tokens()


def test_positive_int_is_the_one_rule_for_count_knobs():
    from crawl.core.text import positive_int
    assert positive_int("42") == 42 and positive_int(" 7 ") == 7
    for bad in ("", "lots", "1.5", "0", "-3"):
        with pytest.raises(ValueError, match="positive whole number"):
            positive_int(bad)


# The prompt size that actually crashed a run: 2,999,828 chars counted
# 1,385,407 tokens against claude-sonnet-5's 1,000,000 ceiling (coderay-cvi).
OVERSIZED_PROMPT = "x" * 2_999_828


def _fake_anthropic_module_that_records_calls(text="ok"):
    """A fake whose stream() records that it was reached, so a test can assert
    the guard fired before any SDK call was made."""
    fake = _fake_anthropic_module_with_usage(
        input_tokens=1, output_tokens=1, cache_read=0, cache_write=0, text=text,
    )
    fake.stream_calls = []
    inner = fake.Anthropic

    class Recording(inner):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            real_stream = self.messages.stream

            def stream(**kwargs):
                fake.stream_calls.append(kwargs)
                return real_stream(**kwargs)

            self.messages.stream = stream

    fake.Anthropic = Recording
    return fake


def _fake_anthropic_module_raising(api_message, status=400):
    """A fake whose stream() raises the SDK's size-refusal class for `status`,
    carrying `api_message` the way a real one does: in a parsed body, with
    str() rendering as `Error code: N - {body}` (anthropic/_base_client.py),
    not as the bare sentence."""
    fake = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        def __init__(self, body):
            self.body = body
            super().__init__(f"Error code: {status} - {body}")

    class BadRequestError(APIStatusError):
        pass

    class RequestTooLargeError(APIStatusError):
        pass

    raised = RequestTooLargeError if status == 413 else BadRequestError
    body = {"type": "error",
            "error": {"type": "invalid_request_error", "message": api_message}}

    class Messages:
        def stream(self, **kwargs):
            raise raised(body)

    class Anthropic:
        def __init__(self, *a, **kw):
            self.messages = Messages()

    fake.APIStatusError = APIStatusError
    fake.BadRequestError = BadRequestError
    fake.RequestTooLargeError = RequestTooLargeError
    fake.Anthropic = Anthropic
    return fake


def test_oversized_prompt_is_refused_before_any_sdk_call(monkeypatch):
    fake = _fake_anthropic_module_that_records_calls()
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    with pytest.raises(call_llm_module.PromptTooLarge) as excinfo:
        call_llm(OVERSIZED_PROMPT)

    assert fake.stream_calls == []
    message = str(excinfo.value)
    assert "claude-sonnet-5" in message
    assert "1,000,000" in message
    assert "--codebase-budget" in message


def test_normal_prompt_is_not_refused(monkeypatch):
    fake = _fake_anthropic_module_that_records_calls(text="fine")
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    assert call_llm("a modest prompt") == "fine"
    assert len(fake.stream_calls) == 1


def test_model_with_no_published_ceiling_skips_the_guard(monkeypatch):
    # An unknown ceiling must mean "don't check", never a guessed number.
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-unpublished-9")
    fake = _fake_anthropic_module_that_records_calls(text="through")
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    assert call_llm(OVERSIZED_PROMPT) == "through"
    assert len(fake.stream_calls) == 1


def test_cached_oversized_prompt_is_served_rather_than_refused(monkeypatch):
    # A prompt already in the cache succeeded once, costs nothing to serve,
    # and reaches no provider -- the guard must not stand in front of it.
    fake = _fake_anthropic_module_that_records_calls()
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    _cache_put("anthropic", "claude-sonnet-5",
               call_llm_module.DEFAULT_MAX_OUTPUT_TOKENS,
               OVERSIZED_PROMPT, "from cache")

    assert call_llm(OVERSIZED_PROMPT) == "from cache"
    assert fake.stream_calls == []


def test_too_long_rejection_from_the_api_is_reported_clearly(monkeypatch):
    # The guard's estimate can be beaten by a denser-than-measured prompt, so
    # the provider's own refusal must still read as a budget problem.
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_raising(
        "prompt is too long: 1385407 tokens > 1000000 maximum"))

    with pytest.raises(call_llm_module.PromptTooLarge) as excinfo:
        call_llm("short enough to pass the estimate")

    message = str(excinfo.value)
    assert "prompt is too long: 1385407 tokens > 1000000 maximum" in message
    assert "--codebase-budget" in message
    assert "LLM_MAX_OUTPUT_TOKENS" in message


def test_the_reported_refusal_carries_no_dict_repr(monkeypatch):
    # The SDK renders str() on a status error as `Error code: N - {body}` with
    # the parsed body inlined, so stringifying the exception drops a dict repr
    # into the middle of the remediation line and buries the two numbers the
    # user needs. The message comes out of the body instead.
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_raising(
        "prompt is too long: 1385407 tokens > 1000000 maximum"))

    with pytest.raises(call_llm_module.PromptTooLarge) as excinfo:
        call_llm("short enough to pass the estimate")

    message = str(excinfo.value)
    assert "Error code:" not in message
    assert "{" not in message and "'" not in message


def test_a_request_over_the_byte_limit_is_reported_as_a_size_problem(monkeypatch):
    # 413 arrives as RequestTooLargeError, a sibling of BadRequestError rather
    # than a subclass, so catching the 400 alone misses it. Its status is the
    # whole diagnosis, so it needs no wording match.
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module_raising(
        "request body too large", status=413))

    with pytest.raises(call_llm_module.PromptTooLarge) as excinfo:
        call_llm("small by token count, past the transport limit by bytes")

    assert "--codebase-budget" in str(excinfo.value)


def test_other_bad_requests_are_left_alone(monkeypatch):
    # Only a size refusal is a budget problem; anything else must keep its own
    # type and message rather than being mislabelled.
    fake = _fake_anthropic_module_raising("temperature: unsupported")
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    with pytest.raises(fake.BadRequestError):
        call_llm("a prompt with a bad parameter")


def test_a_differently_worded_size_refusal_is_not_mistaken_for_one(monkeypatch):
    # The 400 match is a case-sensitive substring of provider copy. Pinning the
    # exact recorded wording documents the assumption: reword it and the
    # handler stops firing, which this test is what reports.
    fake = _fake_anthropic_module_raising("Prompt Is Too Long: 1385407 tokens")
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    with pytest.raises(fake.BadRequestError):
        call_llm("a refusal whose wording drifted")


def test_sdk_size_refusal_classes_are_named(monkeypatch):
    """The handler resolves its catch targets by name off the installed SDK, so
    a rename would leave it matching nothing while every faked test stayed
    green. anthropic is a core dependency, so this needs no network or key."""
    monkeypatch.delitem(sys.modules, "anthropic", raising=False)
    import anthropic

    for name in call_llm_module._SIZE_REFUSAL_NAMES:
        cls = getattr(anthropic, name, None)
        assert isinstance(cls, type), f"anthropic.{name} is gone"
        assert issubclass(cls, Exception), f"anthropic.{name} is not an exception"

    assert len(call_llm_module._size_refusal_errors()) == len(
        call_llm_module._SIZE_REFUSAL_NAMES)


# 1,000,000 tokens at the measured 2.1653 density: the largest prompt that
# genuinely fits under claude-sonnet-5's ceiling. The guard must let it by, or
# it is refusing work that would have succeeded.
LARGEST_FITTING_PROMPT = "x" * 2_165_300


def test_a_large_prompt_that_genuinely_fits_is_not_refused(monkeypatch):
    fake = _fake_anthropic_module_that_records_calls(text="fits")
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    assert call_llm(LARGEST_FITTING_PROMPT) == "fits"
    assert len(fake.stream_calls) == 1


def test_the_guard_admits_a_prompt_estimating_exactly_the_ceiling(monkeypatch):
    # The comparison is `>`, so an estimate landing on the ceiling is allowed.
    fake = _fake_anthropic_module_that_records_calls(text="exact")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    at_ceiling = "x" * int(1_000_000 * call_llm_module.CHARS_PER_TOKEN)

    assert call_llm(at_ceiling) == "exact"
    assert len(fake.stream_calls) == 1


def test_the_guard_refuses_one_token_over_the_ceiling(monkeypatch):
    fake = _fake_anthropic_module_that_records_calls()
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    over = "x" * (int(1_000_000 * call_llm_module.CHARS_PER_TOKEN) + 3)

    with pytest.raises(call_llm_module.PromptTooLarge):
        call_llm(over)
    assert fake.stream_calls == []


def test_the_guard_measures_the_text_actually_sent(monkeypatch):
    # The cache-breakpoint marker is stripped before the prompt goes out, so
    # the marker's own characters must not count toward the estimate.
    fake = _fake_anthropic_module_that_records_calls(text="marker ok")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    body = int(1_000_000 * call_llm_module.CHARS_PER_TOKEN)
    # Over the ceiling with the marker counted, exactly on it without.
    prompt = "x" * (body // 2) + call_llm_module.CACHE_BREAKPOINT + "x" * (body - body // 2)

    assert call_llm(prompt) == "marker ok"
    assert len(fake.stream_calls) == 1


def test_the_refusal_names_the_estimate_it_computed(monkeypatch):
    fake = _fake_anthropic_module_that_records_calls()
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    with pytest.raises(call_llm_module.PromptTooLarge) as excinfo:
        call_llm(OVERSIZED_PROMPT)

    # Pins the formula, not just the fact of a refusal.
    assert "1,199,931" in str(excinfo.value)
    assert "2,999,828" in str(excinfo.value)


def test_an_unguarded_model_is_reported_once_per_run(monkeypatch, capsys):
    # Not guessing a ceiling is right; saying nothing about it is not, or a
    # later provider refusal looks like it came from nowhere.
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-unpublished-9")
    monkeypatch.setitem(sys.modules, "anthropic",
                        _fake_anthropic_module_that_records_calls(text="ok"))
    call_llm_module.reset_usage()

    call_llm("first")
    call_llm("second")

    err = capsys.readouterr().err
    assert err.count("no input-token ceiling recorded") == 1
    assert "claude-unpublished-9" in err


def test_a_deterministic_refusal_is_not_retried_by_a_node():
    """PocketFlow's Node retries on `except Exception`, and a size refusal is
    deterministic, so a retry re-uploads the same prompt to earn the same
    verdict. PromptTooLarge derives from SystemExit to stay out of that."""
    from pocketflow import Node

    attempts = []

    class Refusing(Node):
        def __init__(self):
            super().__init__(max_retries=3, wait=0)

        def exec(self, prep_res):
            attempts.append(1)
            raise call_llm_module._too_large("prompt is about 9 tokens")

    with pytest.raises(call_llm_module.PromptTooLarge):
        Refusing()._exec(None)

    assert len(attempts) == 1


def test_a_deterministic_refusal_still_lets_a_run_keep_its_results(tmp_path):
    """Bypassing the retry loop must not also bypass keeping_results, or a
    refusal throws away every paid result the run already had."""
    from crawl.core.runner import keeping_results

    dumped = []

    def step():
        raise call_llm_module._too_large("prompt is about 9 tokens")

    with pytest.raises(call_llm_module.PromptTooLarge):
        keeping_results(step, {"chapters": ["one"]}, str(tmp_path),
                        lambda shared, out: dumped.append(shared) or "state.json")

    assert dumped == [{"chapters": ["one"]}]


def test_prompt_too_large_is_importable_from_core():
    # ResponseTruncated is re-exported for the node that catches it; a node
    # cannot handle this one by the same convention unless it is too.
    from crawl.core import PromptTooLarge

    assert PromptTooLarge is call_llm_module.PromptTooLarge
