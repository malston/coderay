import glob
import os

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def test_every_prompt_wraps_untrusted_repo_content_in_a_boundary():
    paths = sorted(glob.glob(os.path.join(PROMPTS_DIR, "*.md")))
    assert paths, "expected prompts/*.md to exist"
    for path in paths:
        template = open(path).read()
        assert "{codebase}" in template or "{manifest}" in template
        assert "UNTRUSTED DATA" in template
        assert "<untrusted_" in template


def test_prompt_templates_still_render_with_dummy_args():
    dummy = {
        "chars_per_file": 1, "target_count": 1, "manifest": "", "codebase": "",
        "abstractions": "", "name": "", "description": "", "chapter_num": 1,
        "total": 1, "prev_chapters": "", "chapter_list": "", "instructions": "",
    }
    for path in glob.glob(os.path.join(PROMPTS_DIR, "*.md")):
        template = open(path).read()
        template.format(**dummy)  # raises on a stray brace
