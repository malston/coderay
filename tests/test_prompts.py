import glob
import os

from coderay_utils import fill

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "workflow", "prompts")


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
    from coderay_utils.call_llm import CACHE_BREAKPOINT

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
