"""Shared plumbing for the pipeline's LLM-calling nodes: fill a prompt's
`{slots}`, pull a fenced ```yaml block, and retry a structured call when a
flaky model drops a field or returns malformed YAML.
"""
import os
import re

import yaml

from .call_llm import call_llm


def read_prompt(prompts_dir, name):
    """Read a prompt file. `prompts/` stays the source of truth for every prompt."""
    return open(os.path.join(prompts_dir, name)).read()


def fill(template, **kwargs):
    """Fill {key} slots by literal replacement.

    Unlike str.format, this leaves the prompts' literal JSON/Mermaid examples
    (which contain `{ }`) untouched, so the prompt files stay clean copies."""
    for k, v in kwargs.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def parse_yaml(text):
    """Extract and parse a ```yaml fenced block. Raises so a bad reply retries."""
    m = re.search(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    assert m, f"LLM response missing ```yaml fence. Got:\n{text[:500]}"
    return yaml.safe_load(m.group(1))


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
        try:
            return normalize(parse_yaml(call_llm(prompt + tail)))
        except (AssertionError, yaml.YAMLError, ValueError, KeyError) as e:
            print(f"  yaml_call attempt {k + 1}/{retries} failed: {e}")
            last = e
    raise AssertionError(f"yaml_call gave up after {retries} tries. Last error: {last}")
