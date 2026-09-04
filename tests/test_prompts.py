import glob
import os

from crack.core import fill

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "crack", "analyses", "tour", "prompts")


def test_every_prompt_wraps_untrusted_repo_content_in_a_boundary():
    paths = sorted(glob.glob(os.path.join(PROMPTS_DIR, "*.md")))
    assert paths, "expected prompts/*.md to exist"
    for path in paths:
        template = open(path).read()
        assert "{codebase}" in template or "{manifest}" in template
        assert "UNTRUSTED DATA" in template
        assert "<untrusted_" in template


def test_write_chapter_prompt_puts_stable_blocks_before_the_cache_breakpoint():
    # The codebase block (identical every call in a tour, up to CODEBASE_BUDGET
    # chars) must sit before the cache breakpoint so Anthropic's prefix-based
    # caching can reuse it across chapters -- see coderay-dl8.
    from crack.core.call_llm import CACHE_BREAKPOINT

    path = os.path.join(PROMPTS_DIR, "write-chapter.md")
    template = open(path).read()
    assert CACHE_BREAKPOINT in template

    prefix, _, suffix = template.partition(CACHE_BREAKPOINT)
    for stable in ("{chapter_list}", "{codebase}", "{instructions}"):
        assert stable in prefix, f"{stable} must be before the cache breakpoint"
    for volatile in ("{chapter_num}", "{name}", "{description}", "{prev_chapters}"):
        assert volatile in suffix, f"{volatile} must be after the cache breakpoint"


def test_prompt_templates_still_render_with_dummy_args():
    # fill() does literal {key} replacement rather than str.format(), so a prompt
    # can safely contain literal JSON/Mermaid braces without breaking rendering.
    dummy = {
        "chars_per_file": 1, "target_count": 1, "manifest": "", "codebase": "",
        "selected_files": "",
        "abstractions": "", "name": "", "description": "", "chapter_num": 1,
        "total": 1, "prev_chapters": "", "chapter_list": "", "instructions": "",
    }
    for path in glob.glob(os.path.join(PROMPTS_DIR, "*.md")):
        template = open(path).read()
        rendered = fill(template, **dummy)
        for key in dummy:
            assert "{" + key + "}" not in rendered, f"{path}: unfilled slot {{{key}}}"


# coderay-aph: the house style is one shipped block, injected by read_prompt.
ANALYSES_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "crack", "analyses")
# Prompts that do not carry the block: replies that are parsed, not read (a
# JSON or YAML shape), and the two product-intent prompts whose reader is a
# general undergraduate on purpose, so the engineer-facing voice would
# contradict their task.
OWN_VOICE_PROMPTS = {
    "tour/prompts/select-files.md", "tour/prompts/identify-abstractions.md",
    "tour/prompts/analyze-relationships.md",
    "git_history/prompts/name-eras.md", "git_history/prompts/profile-era.md",
    "product_intent/prompts/competitive-positioning.md",
    "product_intent/prompts/surprises-and-absences.md",
    "product_intent/prompts/pain-scene.md", "product_intent/prompts/variant-sentence.md",
}


def _analysis_prompts():
    paths = sorted(glob.glob(os.path.join(ANALYSES_DIR, "*", "prompts", "*.md")))
    assert len(paths) >= 24
    return {os.path.relpath(p, ANALYSES_DIR): open(p).read() for p in paths}


def test_house_style_block_is_clean_prose():
    from crack.core import house_style
    text = house_style()
    assert "concrete nouns" in text
    assert "—" not in text                       # the block enforces no em dashes; it must obey
    assert not [m for m in __import__("re").findall(r"\{[a-z_]+\}", text)], "an unfilled slot"


def test_read_prompt_fills_the_house_style_slot(tmp_path):
    from crack.core import read_prompt
    (tmp_path / "p.md").write_text("Rules first.\n{house_style}\nThen the task: {codebase}\n", encoding="utf-8")
    text = read_prompt(tmp_path, "p.md")
    assert "{house_style}" not in text
    assert "concrete nouns" in text
    assert "{codebase}" in text                      # only the style slot is filled here


def test_read_prompt_leaves_a_template_without_the_slot_alone(tmp_path):
    from crack.core import read_prompt
    (tmp_path / "p.md").write_text("Return JSON: {codebase}\n", encoding="utf-8")
    assert read_prompt(tmp_path, "p.md") == "Return JSON: {codebase}\n"


def test_every_house_voice_prompt_carries_the_slot_and_no_other_does():
    from crack.core.call_llm import CACHE_BREAKPOINT
    for rel, template in _analysis_prompts().items():
        if rel in OWN_VOICE_PROMPTS:
            assert "{house_style}" not in template, rel
            continue
        assert template.count("{house_style}") == 1, rel
        if CACHE_BREAKPOINT in template:
            assert "{house_style}" in template.partition(CACHE_BREAKPOINT)[0], f"{rel}: slot must be in the cached prefix"


def test_prose_prompts_do_not_restate_the_house_style():
    """The block owns the voice; a prompt that repeats a rule drifts from it."""
    restated = ("seamless", "marketing words", "concrete nouns", "no greetings", "brochure words")
    for rel, template in _analysis_prompts().items():
        if rel in OWN_VOICE_PROMPTS:
            continue
        for phrase in restated:
            assert phrase not in template.lower(), f"{rel} restates: {phrase}"
