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
import tempfile
import time

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "crawl")

# A prompt may embed this literal marker to split a stable, cacheable prefix
# (identical across calls, e.g. a repeated codebase block) from a volatile
# suffix. Only the Anthropic path acts on it -- see coderay-dl8.
CACHE_BREAKPOINT = "<<CODERAY_CACHE_BREAKPOINT>>"

DEFAULT_MAX_OUTPUT_TOKENS = 16384

_usage_log = []


def reset_usage():
    """Clear accumulated usage records. Call once before a pipeline run."""
    _usage_log.clear()


def get_usage():
    """Every usage record accumulated since the last reset_usage()."""
    return list(_usage_log)


def resolve_provider_and_model():
    """The (provider, model) pair call_llm() would use right now, without calling it."""
    provider = _pick()
    return provider, _model_for(provider)


class ResponseTruncated(RuntimeError):
    """The model hit the output cap. Deterministic for a given prompt and cap,
    so callers should not retry it as if it were transient (coderay-q2r.46)."""


def _truncated(detail):
    return ResponseTruncated(f"{detail}; raise LLM_MAX_OUTPUT_TOKENS "
                             f"(currently {max_output_tokens()})")


def max_output_tokens():
    """The max-output-tokens cap call_llm() would use right now, without calling
    it. An empty LLM_MAX_OUTPUT_TOKENS means unset, since .env.example ships it
    blank; anything but a positive whole number stops the run with the
    variable named, before a call is paid for."""
    raw = os.environ.get("LLM_MAX_OUTPUT_TOKENS") or str(DEFAULT_MAX_OUTPUT_TOKENS)
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n <= 0:
        raise SystemExit(f"LLM_MAX_OUTPUT_TOKENS must be a positive whole number of tokens, got {raw!r}")
    return n


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
    path = _cache_path(provider, model, max_out, prompt)
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"provider": provider, "model": model, "response": response}, f)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


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
        with Anthropic().messages.stream(
            model=model,
            max_tokens=max_out,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resp = stream.get_final_message()
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
            raise _truncated("OpenAI response truncated (finish_reason=length)")
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
            raise _truncated(f"Gemini response incomplete (finish_reason={finish_reason})")
        text = resp.text

    if not text:
        raise RuntimeError(f"{provider} returned an empty response")

    _cache_put(provider, model, max_out, plain_prompt, text)
    return text


if __name__ == "__main__":
    print(call_llm("Reply with the single word: ready"))
