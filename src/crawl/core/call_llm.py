"""Shared LLM wrapper used by every node in the pipeline.

Picks the provider based on which env var is set:
  ANTHROPIC_API_KEY  -> Claude (claude-sonnet-5)
  OPENAI_API_KEY     -> OpenAI (gpt-5.6-terra)
  GEMINI_API_KEY     -> Gemini (gemini-3.7-flash)

Override the auto pick with LLM_PROVIDER=anthropic|openai|gemini.
Override the model with ANTHROPIC_MODEL / OPENAI_MODEL / GEMINI_MODEL.

Caching:
  Responses are cached on disk under ~/.cache/crawl/ (or $XDG_CACHE_HOME/crawl
  if set) keyed by sha256 of (provider + model + prompt). The cache survives
  across runs so iterating on downstream code (UI, post processing, README
  copy) costs nothing.

  Disable with LLM_CACHE=0.
  Clear with: rm -rf ~/.cache/crawl

Usage tracking:
  Every call_llm() call appends a token-usage record (reset_usage() to clear
  it, get_usage() to read it back). resolve_provider_and_model() reports what
  provider/model call_llm() would use without making a call.

Smoke test:
  python -m crawl.core.call_llm
"""
import hashlib
import json
import os
import sys
import time

from .files import write_text_atomic
from .pricing import input_ceiling
from .text import positive_int

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "crawl")

# A prompt may embed this literal marker to split a stable, cacheable prefix
# (identical across calls, e.g. a repeated codebase block) from a volatile
# suffix. Only the Anthropic path acts on it -- see coderay-dl8.
CACHE_BREAKPOINT = "<<CODERAY_CACHE_BREAKPOINT>>"

DEFAULT_MAX_OUTPUT_TOKENS = 16384

# Chars per token for the pre-flight size estimate. One refused run measured
# 2,999,828 characters at 1,385,407 tokens, a density of 2.1653 (coderay-cvi);
# that is a single sample of one repository, not a property of source in
# general. The divisor has to stay at or above that density so a prompt of it
# that would have fit is not refused, and at or below 2.999825 so that run is
# still caught: at 3.0 the estimate lands on 999,942 and slips under the
# 1,000,000 ceiling. 2.5 sits between the two. Text sparser than 2.5, such as
# prose or markdown, is over-estimated and can be refused when it would have
# fit; the band between this estimate and a real refusal is covered by the
# provider's own error, caught below.
CHARS_PER_TOKEN = 2.5

# Remediation lines for a size refusal. The pre-flight guard measures the
# input alone, so the input knob is the whole answer there; a provider refusal
# can also mean the input plus the requested output exceeds the window, which
# the output cap governs.
INPUT_HINT = "lower --codebase-budget or the CODEBASE_BUDGET environment variable"
INPUT_OR_OUTPUT_HINT = (INPUT_HINT + ", or lower LLM_MAX_OUTPUT_TOKENS if the "
                        "input plus the requested output is what overran")


def _output_hint():
    return f"raise LLM_MAX_OUTPUT_TOKENS (currently {max_output_tokens()})"

_usage_log = []

# (provider, model) pairs already reported as having no recorded ceiling, so a
# run says it once rather than once per LLM call.
_unguarded_reported = set()


def reset_usage():
    """Clear accumulated usage records. Call once before a pipeline run."""
    _usage_log.clear()
    _unguarded_reported.clear()


def get_usage():
    """Every usage record accumulated since the last reset_usage()."""
    return list(_usage_log)


def resolve_provider_and_model():
    """The (provider, model) pair call_llm() would use right now, without calling it."""
    provider = _pick()
    return provider, _model_for(provider)


class ResponseTruncated(SystemExit):
    """The model hit the output cap. Deterministic for a given prompt and cap,
    so every retry reaches the same verdict, and a retry here re-runs a whole
    generation that is billed again (coderay-q2r.46, coderay-n9j)."""


class PromptTooLarge(SystemExit):
    """The prompt is more input than the model accepts. Deterministic for a
    given prompt and model, so every retry reaches the same verdict, though a
    retry here costs only time since no call is made (coderay-cvi)."""


# The failures no retry can recover from. Both derive from SystemExit, which a
# node's retry loop does not match because it catches Exception; the message
# then reaches the user without a traceback, and `keeping_results` names
# SystemExit so a run still writes the results it already paid for. Bypassing
# the retry loop bypasses `exec_fallback` with it, so a node that must survive
# one of these handles it itself rather than relying on that hook.
DETERMINISTIC_FAILURES = (ResponseTruncated, PromptTooLarge)


def _too_large(detail, hint=INPUT_HINT):
    return PromptTooLarge(f"{detail}; {hint}")


# The two classes a size refusal arrives as: 400 for a prompt over the model's
# input ceiling, 413 for a request over the transport's byte limit. They are
# siblings under APIStatusError, not one a subclass of the other, so catching
# either alone misses the other.
_SIZE_REFUSAL_NAMES = ("BadRequestError", "RequestTooLargeError")


def _size_refusal_errors():
    """The SDK classes above, for matching in an except clause. A name the
    installed SDK does not define is left out rather than failing a live run;
    test_sdk_size_refusal_classes_are_named is what reports that, so a rename
    cannot quietly retire this handler."""
    import anthropic
    found = (getattr(anthropic, name, None) for name in _SIZE_REFUSAL_NAMES)
    return tuple(cls for cls in found if isinstance(cls, type))


def _is_request_too_large(e):
    """Whether the refusal is the transport's byte-limit one, whose status is
    the whole diagnosis."""
    import anthropic
    cls = getattr(anthropic, "RequestTooLargeError", None)
    return isinstance(cls, type) and isinstance(e, cls)


def _api_detail(e):
    """The provider's own sentence out of a structured error body. The SDK
    builds str() on a status error as `Error code: 400 - {body}` with the
    parsed body inlined as a dict repr, which reads badly in the middle of a
    remediation line, so prefer the message the body carries."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return str(e)


def _truncated(detail, hint=None):
    return ResponseTruncated(f"{detail}; {hint or _output_hint()}")


def max_output_tokens():
    """The max-output-tokens cap call_llm() would use right now, without calling
    it. An empty LLM_MAX_OUTPUT_TOKENS means unset, since .env.example ships it
    blank; anything but a positive whole number stops the run with the
    variable named, before a call is paid for."""
    raw = os.environ.get("LLM_MAX_OUTPUT_TOKENS") or str(DEFAULT_MAX_OUTPUT_TOKENS)
    try:
        return positive_int(raw)
    except ValueError as e:
        raise SystemExit(f"LLM_MAX_OUTPUT_TOKENS must be a positive whole number of tokens: {e}") from None


def _record_usage(provider, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, duration_s, cached):
    _usage_log.append({
        "provider": provider, "model": model,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens,
        "duration_s": duration_s, "cached": cached,
    })


def _pick():
    p = os.environ.get("LLM_PROVIDER")
    if p:
        return p.strip().lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    raise RuntimeError(
        "No LLM key set. Export ANTHROPIC_API_KEY or OPENAI_API_KEY or GEMINI_API_KEY."
    )


def _model_for(provider):
    # Defaults aim for "good enough quality, low cost" so a run is cheap to
    # reproduce. Bump to the pro/opus tier if you want the best
    # answers and don't mind the cost.
    #
    # Override per call with ANTHROPIC_MODEL / OPENAI_MODEL / GEMINI_MODEL.
    models = {
        "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "openai":    os.environ.get("OPENAI_MODEL", "gpt-5.6-terra"),
        "gemini":    os.environ.get("GEMINI_MODEL", "gemini-3.7-flash"),
    }
    if provider not in models:
        raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}")
    return models[provider]


def _cache_path(provider, model, max_out, prompt):
    key = hashlib.sha256(f"{provider}|{model}|{max_out}|{prompt}".encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(provider, model, max_out, prompt):
    if os.environ.get("LLM_CACHE", "1") == "0":
        return None
    path = _cache_path(provider, model, max_out, prompt)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["response"]
    except (OSError, ValueError, KeyError):
        return None


def _cache_put(provider, model, max_out, prompt, response):
    if os.environ.get("LLM_CACHE", "1") == "0":
        return
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
    os.chmod(CACHE_DIR, 0o700)
    write_text_atomic(_cache_path(provider, model, max_out, prompt),
                      json.dumps({"provider": provider, "model": model, "response": response}), mode=0o600)


def call_llm(prompt: str) -> str:
    provider = _pick()
    model = _model_for(provider)
    max_out = max_output_tokens()

    # The real breakpoint is the last occurrence of the marker in the
    # *template* -- but write-chapter.md's volatile suffix includes
    # {prev_chapters}, LLM-generated text derived from untrusted repo
    # content. If a planted marker ever got echoed into a chapter, it would
    # land after the real breakpoint and rpartition would split there
    # instead, degrading to a cache miss at best and an empty content block
    # at worst. Require both sides non-empty so a pathological split like
    # that is ignored rather than sent to the provider.
    prefix, sep, suffix = prompt.rpartition(CACHE_BREAKPOINT)
    if sep and not (prefix and suffix):
        prefix, sep, suffix = "", "", prompt
    plain_prompt = prefix + suffix if sep else prompt

    # Cache on plain_prompt (marker stripped) -- every provider actually
    # receives that text (Anthropic as a split content list, others as a
    # single string), so the key should match what was actually sent.
    cached = _cache_get(provider, model, max_out, plain_prompt)
    if cached is not None:
        _record_usage(provider, model, 0, 0, 0, 0, 0.0, cached=True)
        return cached

    # Sits after the cache lookup: a cached prompt already succeeded once and
    # reaches no provider, so its size is no longer anyone's problem.
    ceiling = input_ceiling(provider, model)
    if ceiling is None:
        # No figure is recorded, so nothing is checked. Said once per model,
        # because the alternative to a guess is silence and silence leaves a
        # later provider refusal looking like it came from nowhere.
        if (provider, model) not in _unguarded_reported:
            _unguarded_reported.add((provider, model))
            print(f"Warning: no input-token ceiling recorded for {provider}/{model}; "
                  "an oversized prompt will be refused by the provider rather than "
                  "caught before the call", file=sys.stderr)
    else:
        estimate = int(len(plain_prompt) / CHARS_PER_TOKEN)
        if estimate > ceiling:
            raise _too_large(
                f"prompt is about {estimate:,} tokens "
                f"({len(plain_prompt):,} characters), over {model}'s "
                f"{ceiling:,}-token input ceiling")

    start = time.perf_counter()

    if provider == "anthropic":
        from anthropic import Anthropic
        content = [
            {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": suffix},
        ] if sep else prompt
        # Streaming, not create(): the SDK refuses a non-streaming call whose
        # max_tokens implies more than 10 minutes of generation time, which
        # backend's 32768-token cap trips. get_final_message() assembles the
        # stream into the same Message object create() would have returned.
        try:
            with Anthropic().messages.stream(
                model=model,
                max_tokens=max_out,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                resp = stream.get_final_message()
        except _size_refusal_errors() as e:
            # The estimate above is beaten by a prompt that tokenizes denser
            # than the sample it came from, and skipped outright for a model
            # with no ceiling recorded, so the provider's own refusal is
            # restated as the budget problem it is. A 413 is a size refusal by
            # status, so it needs no wording match; a 400 covers many request
            # faults and is identified by the sentence the body carries. Any
            # other refusal keeps its own type and message.
            detail = _api_detail(e)
            if _is_request_too_large(e) or "prompt is too long" in detail:
                raise _too_large(detail, INPUT_OR_OUTPUT_HINT) from e
            raise
        duration_s = time.perf_counter() - start
        usage = getattr(resp, "usage", None)
        if usage is None:
            raise RuntimeError(f"{provider} response missing usage data")
        _record_usage(
            provider, model,
            getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0,
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
            duration_s, cached=False,
        )
        if resp.stop_reason == "max_tokens":
            raise _truncated("Anthropic response truncated (stop_reason=max_tokens)")
        if resp.stop_reason == "model_context_window_exceeded":
            # The window spans the response, so input plus max_tokens can pass
            # the input check and still run out mid-generation. Raising the
            # output cap cannot help, and the partial text must not pass for a
            # whole answer (coderay-8vk).
            raise _truncated(
                "Anthropic stopped at the context window "
                "(stop_reason=model_context_window_exceeded): the input plus "
                "the requested output did not fit", INPUT_OR_OUTPUT_HINT)
        text_block = next((b for b in resp.content if getattr(b, "type", None) == "text"), None)
        text = text_block.text if text_block else None

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
        if usage is None:
            raise RuntimeError(f"{provider} response missing usage data")
        _record_usage(
            provider, model,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            0, 0,
            duration_s, cached=False,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            # One reason for two causes: the requested output cap, or the
            # context window that spans input and output together. Since the
            # reply cannot say which, the remedy names both rather than
            # advising a raise that would make the second case worse.
            raise _truncated("OpenAI response truncated (finish_reason=length)",
                             INPUT_OR_OUTPUT_HINT)
        text = choice.message.content

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
        if usage is None:
            raise RuntimeError(f"{provider} response missing usage data")
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        prompt_total = getattr(usage, "prompt_token_count", 0) or 0
        _record_usage(
            provider, model,
            prompt_total - cached,
            getattr(usage, "candidates_token_count", 0) or 0,
            cached,
            0,
            duration_s, cached=False,
        )
        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = str(getattr(candidate, "finish_reason", "") or "")
        if candidate is not None and finish_reason and "STOP" not in finish_reason.upper():
            # MAX_TOKENS is the only FinishReason that means the output cap.
            # The rest (SAFETY, RECITATION, LANGUAGE, OTHER, BLOCKLIST,
            # PROHIBITED_CONTENT, SPII, MALFORMED_FUNCTION_CALL and the image
            # variants) are content and function-call blocks, several of them
            # sampling-dependent, so another attempt can complete where this
            # one stopped. Calling one a truncation would advise a knob that
            # cannot fix it and, because a truncation leaves the retry loop,
            # would end the run on the first attempt.
            if "MAX_TOKENS" in finish_reason.upper():
                raise _truncated(f"Gemini response incomplete (finish_reason={finish_reason})")
            raise RuntimeError(f"Gemini stopped early (finish_reason={finish_reason})")
        text = resp.text

    if not text:
        raise RuntimeError(f"{provider} returned an empty response")

    _cache_put(provider, model, max_out, plain_prompt, text)
    return text


if __name__ == "__main__":
    print(call_llm("Reply with the single word: ready"))
