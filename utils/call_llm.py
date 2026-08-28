"""Shared LLM wrapper used by every node in the pipeline.

Picks the provider based on which env var is set:
  ANTHROPIC_API_KEY  -> Claude (claude-sonnet-4-6)
  OPENAI_API_KEY     -> OpenAI (gpt-4o)
  GEMINI_API_KEY     -> Gemini (gemini-2.5-flash)

Override the auto pick with LLM_PROVIDER=anthropic|openai|gemini.
Override the model with ANTHROPIC_MODEL / OPENAI_MODEL / GEMINI_MODEL.

Caching:
  Responses are cached on disk under ~/.cache/coderay/ (or $XDG_CACHE_HOME/coderay
  if set) keyed by sha256 of (provider + model + prompt). The cache survives
  across runs so iterating on downstream code (UI, post processing, README
  copy) costs nothing.

  Disable with LLM_CACHE=0.
  Clear with: rm -rf ~/.cache/coderay

Smoke test:
  python -m utils.call_llm
"""
import hashlib
import json
import os
import tempfile

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "coderay")


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
    # Defaults aim for "good enough quality, low cost" so the chapter examples
    # are cheap to reproduce. Bump to the pro/opus tier if you want the best
    # answers and don't mind the cost.
    #
    # Override per call with ANTHROPIC_MODEL / OPENAI_MODEL / GEMINI_MODEL.
    models = {
        "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "openai":    os.environ.get("OPENAI_MODEL", "gpt-5.1"),
        "gemini":    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
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
    os.makedirs(CACHE_DIR, exist_ok=True)
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
    max_out = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "16384"))

    cached = _cache_get(provider, model, max_out, prompt)
    if cached is not None:
        return cached

    if provider == "anthropic":
        from anthropic import Anthropic
        resp = Anthropic().messages.create(
            model=model,
            max_tokens=max_out,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Anthropic response truncated (stop_reason=max_tokens)")
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
            messages=[{"role": "user", "content": prompt}],
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("OpenAI response truncated (finish_reason=length)")
        text = choice.message.content

    elif provider == "gemini":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_out),
        )
        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = str(getattr(candidate, "finish_reason", "") or "")
        if candidate is not None and finish_reason and "STOP" not in finish_reason.upper():
            raise RuntimeError(f"Gemini response incomplete (finish_reason={finish_reason})")
        text = resp.text

    if not text:
        raise RuntimeError(f"{provider} returned an empty response")

    _cache_put(provider, model, max_out, prompt, text)
    return text


if __name__ == "__main__":
    print(call_llm("Reply with the single word: ready"))
