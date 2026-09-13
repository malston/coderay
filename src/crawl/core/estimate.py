"""Size a run's tokens and cost before any of it is paid for.

Each analysis contributes a list of `Prompt` records through its own
`prompt_plan(args, preview)`; the arithmetic, the input-ceiling check, and the
pricing happen once, here. See docs/prompt-anatomy.md for what a prompt is made
of, and docs/superpowers/specs/2026-09-12-token-estimate-design.md for why the
contract has this shape.
"""
import textwrap
from dataclasses import dataclass

from .call_llm import CHARS_PER_TOKEN
from .pricing import cost_for, input_ceiling

# Input tokens for pricing use a plain chars/4 heuristic. The ceiling check
# below uses call_llm's own CHARS_PER_TOKEN instead: the point there is to
# predict that guard's verdict rather than to price the run, and the guard is
# deliberately more conservative.
PRICING_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Prompt:
    """One prompt an analysis sends, sized without calling an LLM.

    `calls` is a (low, high) pair. The two are equal when the count is fixed.
    They differ when the model decides it, and then each bound is read from the
    prompt or flag that sets it rather than guessed (tests/test_call_bounds.py).
    A low of zero is a real answer for a prompt that may not fire at all.

    `note` carries what the numbers alone would misstate: repository text this
    prompt carries that no pre-flight step can size, most of all.

    `body_max_chars` is the most this prompt could carry where that differs
    from what it likely will. The cost figure wants the expectation and the
    refusal prediction wants the ceiling, so a guard whose whole job is to
    speak before a run is refused is not the thing that stays quiet
    (coderay-8vk, coderay-3le). Leave it None where a crawler knows exactly
    what it sends, and the two coincide.
    """
    template: str
    shell_chars: int
    body_chars: int
    calls: tuple[int, int]
    note: str = ""
    body_max_chars: int | None = None

    @property
    def chars_per_call(self):
        return self.shell_chars + self.body_chars

    @property
    def ceiling_chars(self):
        """The most this prompt could be, for the input-ceiling check."""
        return self.shell_chars + (self.body_chars if self.body_max_chars is None
                                   else self.body_max_chars)


def shell_chars(prompts_dir, name, slots):
    """A template's own characters, with its slot placeholders subtracted.

    `read_prompt` has already filled {house_style} for the templates that carry
    it, so the figure this returns includes that block where it applies. `slots`
    is the analysis's own list of the slots its node fills at prep time.
    """
    from .llm import read_prompt
    text = read_prompt(prompts_dir, name)
    return len(text) - sum(len("{%s}" % s) for s in slots)


def overview_prompt():
    """The shared OverviewNode's prompt (crawl/core/overview.py), for the five
    analyses that end with it.

    It is a string constant rather than a file under a prompts/ directory, and
    it takes the voice block without the evidence rules, since it is handed
    counts and gists rather than source. It carries no repository text, so it
    costs the same on any repo. Each analysis adds a few hundred characters of
    section titles, gists and facts on top, which are not counted here.
    """
    from .llm import house_style
    from .overview import _PROMPT
    slots = ("name", "what", "facts", "sections", "headers", "house_style")
    shell = len(_PROMPT) - sum(len("{%s}" % s) for s in slots)
    return Prompt("(shared OverviewNode)", shell + len(house_style(with_evidence=False)),
                  0, (1, 1))


# What to price against when no key is set. A user sizing a run before paying
# for it has not necessarily paid yet, so the command answers anyway and says
# which model it assumed rather than quietly picking one.
ASSUMED = ("anthropic", "claude-sonnet-5")


def resolve_for_estimate():
    """(provider, model, assumed). Falls back rather than refusing to answer."""
    from .call_llm import resolve_provider_and_model
    try:
        return (*resolve_provider_and_model(), False)
    except RuntimeError:
        return (*ASSUMED, True)


def estimate(prompts, provider, model, max_output_tokens, assumed=False):
    """What a run of these prompts would send, cost, and whether it would be
    refused before its first call.

    `max_output_tokens` is passed in rather than read here, because four of the
    seven analyses raise LLM_MAX_OUTPUT_TOKENS through their own ENV_DEFAULTS.
    Reading the ambient value would report the wrong worst case for those four.
    """
    low = sum(p.chars_per_call * p.calls[0] for p in prompts) // PRICING_CHARS_PER_TOKEN
    high = sum(p.chars_per_call * p.calls[1] for p in prompts) // PRICING_CHARS_PER_TOKEN
    worst_case_output = max_output_tokens * sum(p.calls[1] for p in prompts)

    ceiling = input_ceiling(provider, model)
    largest = max((p.ceiling_chars for p in prompts), default=0)
    largest_tokens = int(largest / CHARS_PER_TOKEN)

    return {
        "provider": provider,
        "model": model,
        "assumed": assumed,
        "input_tokens": (low, high),
        "output_tokens_worst_case": worst_case_output,
        "cost": (_cost(provider, model, low, 0),
                 _cost(provider, model, high, worst_case_output)),
        "input_ceiling": ceiling,
        "largest_prompt_tokens": largest_tokens,
        # None, not False, when no ceiling is recorded: unchecked is not the
        # same answer as fits, and pricing.input_ceiling sets that rule.
        "over_ceiling": None if ceiling is None else largest_tokens > ceiling,
        "notes": [p.note for p in prompts if p.note],
        "prompts": list(prompts),
    }


def _cost(provider, model, input_tokens, output_tokens):
    return cost_for(provider, model, {
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
    })


def format_estimate(e, codebase_budget=None):
    """The estimate a reader sees, under the crawl counts.

    Ranges print as a range. A figure the estimate cannot know is named in a
    note rather than folded into a number, the rule the Preview contract set:
    absent and said, never silently zero.
    """
    low, high = e["input_tokens"]
    assumed = " (assumed: no LLM key is set)" if e.get("assumed") else ""
    lines = ["", f"  Model:           {e['provider']}/{e['model']}{assumed}"]
    if codebase_budget is not None:
        # coderay-5wu.15: a user comparing budgets needs to see which one
        # produced the number in front of them.
        lines.append(f"  Codebase budget: {codebase_budget:,} chars")
    lines += [f"  Input tokens:    {_range(low, high)}",
              f"  Output tokens:   up to {e['output_tokens_worst_case']:,} (worst case: "
              "every call hits the cap)"]

    cost_low, cost_high = e["cost"]
    if cost_low is None or cost_high is None:
        lines.append(f"  Cost:            unknown (no pricing recorded for {e['model']})")
    else:
        lines.append(f"  Cost:            ${cost_low:,.4f} to ${cost_high:,.4f}")

    lines.append("")
    lines.append("  Prompt                          calls     tokens each")
    for p in e["prompts"]:
        tokens = p.chars_per_call // PRICING_CHARS_PER_TOKEN
        lines.append(f"    {p.template:<28}{_range(*p.calls):>9}{tokens:>14,}")

    for note in (*e["notes"], *_verdict(e)):
        lines += ["", *textwrap.wrap(note, width=76, initial_indent="  NOTE: ",
                                     subsequent_indent="        ")]
    lines += ["", *textwrap.wrap(
        "This estimate does not account for prompt caching: a run reuses the same "
        "text across calls, so the real cost is often under the low end.",
        width=76, initial_indent="  ", subsequent_indent="  ")]
    return "\n".join(lines)


def _range(low, high):
    return f"{low:,}" if low == high else f"{low:,} to {high:,}"


def _verdict(e):
    """Whether a real run would be refused before it spent anything (coderay-8vk)."""
    ceiling, largest = e["input_ceiling"], e["largest_prompt_tokens"]
    if ceiling is None:
        return ["No input ceiling is recorded for this model, so a prompt too large "
                "for it would be refused by the provider rather than caught before "
                "the call."]
    if e["over_ceiling"]:
        return [f"This run would be refused before its first call: its largest prompt "
                f"is about {largest:,} tokens, over {e['model']}'s {ceiling:,}-token "
                f"input ceiling. Lower --codebase-budget."]
    return []
