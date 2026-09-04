"""Shared plumbing for the pipeline's LLM-calling nodes: fill a prompt's
`{slots}`, pull a fenced ```yaml block, and retry a structured call when a
flaky model drops a field or returns malformed YAML.
"""
import json
import re
from importlib import resources

import yaml

from .call_llm import call_llm

HOUSE_STYLE_SLOT = "{house_style}"


def _core_prompt(name):
    return (resources.files("crawl.core") / "prompts" / name).read_text(encoding="utf-8").strip()


def house_style(with_evidence=True):
    """The voice every report is written in: one shipped block, the single
    source for the rules, read by the model at generation time and by anyone
    writing or editing a prompt (coderay-aph). A prompt whose reader is
    deliberately not an engineer (product-intent's pain scene and variant
    sentence) keeps its own voice and has no slot.

    The evidence rules (cite file and symbol, trace one real path) ride along
    by default. A prompt that is handed no source, only counts and section
    gists like the overview, passes with_evidence=False so the model is not
    told to cite what it cannot see."""
    text = _core_prompt("house-style.md")
    if with_evidence:
        text += "\n\n" + _core_prompt("evidence-discipline.md")
    return text


def read_prompt(prompts_dir, name):
    """Read a prompt file from a directory (an importlib.resources Traversable
    or a pathlib.Path). `crawl/analyses/tour/prompts/` stays the source of truth
    for every prompt.

    A prompt that writes prose carries `{house_style}` in its static prefix and
    gets the shared block filled here, so no prompt restates the voice rules; a
    prompt whose reply is parsed (JSON, YAML) has no slot and is returned as is."""
    template = (prompts_dir / name).read_text(encoding="utf-8")
    if HOUSE_STYLE_SLOT in template:
        template = template.replace(HOUSE_STYLE_SLOT, house_style())
    return template


def fill(template, **kwargs):
    """Fill {key} slots by literal replacement.

    Unlike str.format, this leaves the prompts' literal JSON/Mermaid examples
    (which contain `{ }`) untouched, so the prompt files stay clean copies."""
    for k, v in kwargs.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def extract_mermaid(md, kind=None):
    """Pull the body of the first matching ```mermaid fence, or "" if none match.

    `kind` narrows it to a diagram type ("erDiagram", "sequenceDiagram"): a
    reply that opens with a flowchart and puts the ERD second would otherwise
    hand the caller the wrong diagram. Without it the first fence wins, which
    is what every caller but schema wants."""
    for m in re.finditer(r"```mermaid\s*\n(.*?)```", md or "", re.DOTALL):
        body = m.group(1).strip()
        if kind is None or body.startswith(kind):
            return body
    return ""


def parse_json(text):
    """Decode the first JSON value in a reply. Starts after a ```json fence if
    present, but uses raw_decode (not a closing-fence regex) so a nested code or
    ```mermaid block inside a string value can't truncate the parse. Raises so a
    bad reply retries."""
    m = re.search(r"```json[ \t]*\n", text)
    search = text[m.end():] if m else text
    decoder = json.JSONDecoder()
    for i, ch in enumerate(search):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(search[i:])
                return obj
            except ValueError:
                continue
    raise AssertionError(f"No JSON found in LLM response. Got:\n{text[:500]}")


def parse_yaml(text):
    """Extract and parse a ```yaml fenced block. Raises so a bad reply retries."""
    m = re.search(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if not m:
        raise ValueError(f"LLM response missing ```yaml fence. Got:\n{text[:500]}")
    return yaml.safe_load(m.group(1))


# What a bad REPLY can raise, as opposed to a broken transport. TypeError and
# AttributeError are here because normalize() sees whatever the model returned:
# `"name" in 42` raises TypeError and `[].get(...)` raises AttributeError, and
# without them a wrong-shaped reply skips all four retries AND the caller's
# fallback, killing the run. That was coderay-q2r.18, fixed then at the call
# site; this is the root (coderay-q2r.33). Transport errors are deliberately
# NOT here -- they belong to the node's own max_retries.
_REPLY_ERRORS = (AssertionError, ValueError, KeyError, TypeError, AttributeError,
                 yaml.YAMLError)


def json_call(prompt, normalize, retries=4):
    """Call the model, parse its JSON reply, and validate/normalize it.

    The JSON twin of yaml_call: on a bad or incomplete reply -- a flaky model
    drops a required field on a very large prompt -- retry with a changed tail,
    which nudges the model to return the whole schema and dodges the response
    cache so the retry is genuinely fresh. Network errors are NOT caught; they
    bubble up to the node's own max_retries."""
    last = None
    for k in range(retries):
        tail = "" if k == 0 else (
            f"\n\nReturn COMPLETE JSON with every required top-level field. (retry {k})")
        reply = call_llm(prompt + tail)  # outside the try: its errors are not bad replies (coderay-q2r.41)
        try:
            return normalize(parse_json(reply))
        except _REPLY_ERRORS as e:
            print(f"  json_call attempt {k + 1}/{retries} failed: {e}")
            last = e
    raise AssertionError(f"json_call gave up after {retries} tries. Last error: {last}")


def yaml_call(prompt, normalize, retries=4):
    """Call the model, parse its ```yaml reply, and validate/normalize it.

    On a bad or incomplete reply, retry with a changed prompt tail -- an
    unescaped quote inside a quoted string is the common failure, and varying
    the tail both nudges the model to fix its quoting and dodges the response
    cache (so the retry is genuinely fresh, not a replay of the cached miss).
    Network errors are NOT caught here; they bubble up to the node's own
    max_retries."""
    last = None
    for k in range(retries):
        tail = "" if k == 0 else (
            f"\n\nReturn VALID YAML: put every string value in double quotes and "
            f"escape any double quote inside it as \\\". (retry {k})")
        reply = call_llm(prompt + tail)  # outside the try: its errors are not bad replies (coderay-q2r.41)
        try:
            return normalize(parse_yaml(reply))
        except _REPLY_ERRORS as e:
            print(f"  yaml_call attempt {k + 1}/{retries} failed: {e}")
            last = e
    raise AssertionError(f"yaml_call gave up after {retries} tries. Last error: {last}")
