# Backend Analysis Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `crack backend <repo>` as a second analysis, together with the shared card-family render engine the next three ports reuse.

**Architecture:** Copy the sibling fork's finished `core/render.py` card engine, `OverviewNode`, overview writer, and `env_defaults` into `crack/core/`, add a `run_analysis()` helper beside the existing `run_flow()`, then add `crack/analyses/backend/` as the first analysis to declare `SECTIONS`/`THEME`. `tour` is not modified. A committed golden `index.html`/`index.md` pair proves the port reproduces its source byte for byte.

**Tech Stack:** Python 3, PocketFlow, markdown-it-py (already a dependency), pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-01-analysis-port-design.md`

**Bead:** coderay-q2r.1 (child of epic coderay-q2r)

## Global Constraints

- **Port source of record:** `~/code/Crack-Any-Codebase-with-AI`, branch `main`, commit `34f0ad2`. Referred to below as `$SIB`. Verify with `git -C ~/code/Crack-Any-Codebase-with-AI rev-parse main` before copying anything; it must print `34f0ad2a7044284555911590ca3773c92e1244ac`.
- **No new dependencies.** `markdown-it-py>=4.2.0,<5` is already in `pyproject.toml`.
- **`tour` is not modified.** No file under `src/crack/analyses/tour/` changes in this plan. `src/crack/cli.py` does not change either.
- **Prompt loading uses `importlib.resources`**, never `os.path.join(os.path.dirname(__file__), ...)`. coderay's `read_prompt(prompts_dir, name)` does `(prompts_dir / name).read_text(encoding="utf-8")`, so it needs a Traversable or `Path`, not a `str`.
- **Output directory default** is `<cwd>/output/<repo-name>-<analysis-name>`, matching `tour`'s `default_output_dir`. Not the sibling's `output/<repo>/<analysis>`.
- **No em dashes in prose** (docs, comments, docstrings). Use `--` or rewrite. Copied source that already contains them in LLM-facing prompt text or in card copy stays as-is; that is data, not our prose.
- **Tests need no network and no API key.** Fake at the `call_llm` / `yaml_call` boundary.
- **Every file read and write passes an explicit `encoding="utf-8"`.** A C locale, which is the
  default in many containers and CI images, otherwise picks ASCII, and the prompt and report text
  carries non-ASCII (em dashes, `·`, `§`). On a read that kills the run before it does any work;
  on a report write it kills the run *after* every LLM call has been made and paid for, losing
  the whole output. The port source hit both and fixed them in commits 61b2573 and its follow-up.
- **Every test run is** `uv run python -m pytest tests/ -q` from the worktree root. Baseline before this plan: 145 passed.
- **The `N passed` figures** in each task are running totals assuming every prior task landed its tests exactly as written. A small drift is fine; a failure is not.
- **Conventional commits**, one per task, as spelled out in each task's final step.

## File Structure

Created:

| Path                                                                | Responsibility                                                                                                                          |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/crack/core/env.py`                                             | `env_defaults` context manager: apply an analysis's env defaults for one run                                                            |
| `src/crack/core/render.py`                                          | `Section`, `Theme`, the card-family page engine, and the markdown/escaping helpers                                                      |
| `src/crack/core/overview.py`                                        | `write_overview`: one LLM call for the page welcome and per-section intros                                                              |
| `src/crack/core/nodes.py`                                           | `OverviewNode`, the reusable PocketFlow node wrapping `write_overview`                                                                  |
| `src/crack/analyses/backend/__init__.py`                            | the backend analysis: `NAME`, `SECTIONS`, `THEME`, `ENV_DEFAULTS`, `build_flow`, `add_arguments`, `init_shared`, `run`, `overview_spec` |
| `src/crack/analyses/backend/backend_crawl.py`                       | classify a repo's source into the six layers, build the bundle                                                                          |
| `src/crack/analyses/backend/nodes.py`                               | `BuildBundle`, `Pipeline`, `LayerCode`, `Trace`                                                                                         |
| `src/crack/analyses/backend/prompts/{pipeline,layer-code,trace}.md` | the three LLM prompts                                                                                                                   |
| `scripts/regen_golden.py`                                           | regenerate a golden fixture from the sibling checkout                                                                                   |
| `tests/fixtures/golden/backend/{shared.json,index.html,index.md}`   | the golden fixture                                                                                                                      |

Modified:

| Path                                  | Change                                                                        |
| ------------------------------------- | ----------------------------------------------------------------------------- |
| `src/crack/core/llm.py`               | add `extract_mermaid`                                                         |
| `src/crack/core/__init__.py`          | re-export `extract_mermaid`, `OverviewNode`, `write_overview`, `env_defaults` |
| `src/crack/core/runner.py`            | add `run_analysis(analysis, args)` beside `run_flow`                          |
| `src/crack/analyses/__init__.py`      | register `backend` in `ANALYSES`                                              |
| `pyproject.toml`                      | add the `crack.analyses.backend` package and its prompt package-data          |
| `README.md`, `CLAUDE.md`, `AGENTS.md` | document the second subcommand                                                |

---

### Task 1: `env_defaults` context manager

**Files:**

- Create: `src/crack/core/env.py`
- Modify: `src/crack/core/__init__.py`
- Test: `tests/test_env.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `crack.core.env.env_defaults(defaults: dict) -> contextmanager`, also re-exported as `crack.core.env_defaults`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_env.py`:

```python
import os

from crack.core import env_defaults

def test_sets_absent_key_and_restores_it():
    assert "CRACK_TEST_ABSENT" not in os.environ
    with env_defaults({"CRACK_TEST_ABSENT": "32768"}):
        assert os.environ["CRACK_TEST_ABSENT"] == "32768"
    assert "CRACK_TEST_ABSENT" not in os.environ

def test_a_value_the_user_already_set_wins(monkeypatch):
    monkeypatch.setenv("CRACK_TEST_PRESENT", "mine")
    with env_defaults({"CRACK_TEST_PRESENT": "theirs"}):
        assert os.environ["CRACK_TEST_PRESENT"] == "mine"
    assert os.environ["CRACK_TEST_PRESENT"] == "mine"

def test_restores_on_exception():
    try:
        with env_defaults({"CRACK_TEST_RAISES": "1"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "CRACK_TEST_RAISES" not in os.environ

def test_empty_defaults_is_a_no_op():
    with env_defaults({}):
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_env.py -q`
Expected: FAIL, `ImportError: cannot import name 'env_defaults' from 'crack.core'`

- [ ] **Step 3: Copy the implementation from the sibling**

Run:

```bash
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/core/env.py src/crack/core/env.py
```

The file is 24 lines and needs no edits. Confirm its content matches:

```python
"""Apply an analysis's environment defaults for the length of one run."""
import contextlib
import os

@contextlib.contextmanager
def env_defaults(defaults):
    """Set each key only when it is absent, then restore the prior environment.

    A value the user already set always wins. Restoring on exit keeps one
    analysis's default from leaking into the next under `crack all`.
    """
    prior = {}
    try:
        for key, value in defaults.items():
            prior[key] = os.environ.get(key)
            if prior[key] is None:
                os.environ[key] = value
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
```

- [ ] **Step 4: Re-export it**

In `src/crack/core/__init__.py`, add after the `.crawl` import block:

```python
from .env import env_defaults  # noqa: F401
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 149 passed.

- [ ] **Step 6: Commit**

```bash
git add src/crack/core/env.py src/crack/core/__init__.py tests/test_env.py
git commit -m "feat(core): add env_defaults for per-analysis environment defaults"
```

---

### Task 2: `extract_mermaid`

**Files:**

- Modify: `src/crack/core/llm.py`, `src/crack/core/__init__.py`
- Test: `tests/test_llm.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `crack.core.extract_mermaid(md: str) -> str`. Returns the first fenced mermaid block's body, stripped, or `""` when there is none.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm.py`:

````python
def test_extract_mermaid_returns_the_first_block_body():
    from crack.core import extract_mermaid
    md = "intro\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\ntail\n"
    assert extract_mermaid(md) == "flowchart LR\n  a --> b"

def test_extract_mermaid_returns_empty_when_absent():
    from crack.core import extract_mermaid
    assert extract_mermaid("no diagram here") == ""
    assert extract_mermaid("") == ""
    assert extract_mermaid(None) == ""

def test_extract_mermaid_ignores_a_non_mermaid_fence():
    from crack.core import extract_mermaid
    assert extract_mermaid("```python\nx = 1\n```") == ""
````

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_llm.py -q`
Expected: FAIL, `ImportError: cannot import name 'extract_mermaid'`

- [ ] **Step 3: Add the function**

In `src/crack/core/llm.py`, add after `fill`:

````python
def extract_mermaid(md):
    """Pull the body of the first ```mermaid fence, or "" when there is none."""
    m = re.search(r"```mermaid\s*\n(.*?)```", md or "", re.DOTALL)
    return m.group(1).strip() if m else ""
````

`re` is already imported at the top of the file.

- [ ] **Step 4: Re-export it**

In `src/crack/core/__init__.py`, add `extract_mermaid,` to the existing `from .llm import (...)` block, after `fill,`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 152 passed.

- [ ] **Step 6: Commit**

```bash
git add src/crack/core/llm.py src/crack/core/__init__.py tests/test_llm.py
git commit -m "feat(core): add extract_mermaid for diagram-bearing LLM replies"
```

---

### Task 3: the card-family render engine

**Files:**

- Create: `src/crack/core/render.py`
- Test: `tests/test_core_render.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces, all importable from `crack.core.render`:
  - `Section(number, label, note, rail, width, key, when_empty="always", skip_note=None, md_skip_note=None, prefix=None, cards=None)` -- a frozen dataclass.
  - `Theme(title_suffix, eyebrow, accent, accent_soft, hero_from, hero_to, eyebrow_color, eyebrow_bar, sub_color, card_top_from, subtitle, footer, md_preamble, hero_prefix=None, page_name=None)` -- a frozen dataclass. `subtitle`, `footer`, `md_preamble` and `hero_prefix` are `Callable[[dict], str]`; `page_name` is `Callable[[dict, str], str]`.
  - `md(text) -> str`, `md_rich(text) -> str`, `esc(s) -> str`
  - `extract_mermaid(text) -> str`, `strip_mermaid(text) -> str`
  - `split_cards(markdown) -> list[tuple[str, str]]`
  - `card(header_md, body_md) -> str`, `section(spec, cards_html, prefix_html="", intro="") -> str`
  - `render_html(analysis, name, shared) -> str`, `render_markdown(analysis, name, shared) -> str` -- both defer to the analysis's own `render_html`/`render_markdown` when it defines one.

Note: this module defines its own `extract_mermaid` (no `kind` argument) separate from Task 2's in `core/llm.py`. Both exist on the sibling and both are used. Leave both; consolidating them is out of scope for this plan.

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_render.py`:

````python
import pytest

from crack.core.render import (Section, Theme, card, esc, extract_mermaid, md,
                               md_rich, render_html, render_markdown,
                               split_cards, strip_mermaid)

def test_md_unwraps_a_single_paragraph():
    assert md("hello **world**") == "hello <strong>world</strong>"

def test_md_keeps_multiple_paragraphs_wrapped():
    assert md("one\n\ntwo").startswith("<p>")

def test_md_handles_none():
    assert md(None) == ""

def test_md_rich_turns_a_mermaid_fence_into_a_pre_block():
    out = md_rich("```mermaid\nflowchart LR\n  a --> b\n```")
    assert '<pre class="mermaid">' in out
    assert "language-mermaid" not in out

def test_md_does_not_pass_through_raw_html():
    assert "<script>" not in md("<script>alert(1)</script>")

def test_esc_escapes_and_strips():
    assert esc("  <b>&  ") == "&lt;b&gt;&amp;"

def test_split_cards_splits_on_h3_and_drops_the_preamble():
    assert split_cards("intro\n\n### A\nbody a\n\n### B\nbody b") == [
        ("A", "body a"), ("B", "body b")]

def test_split_cards_of_empty_is_empty():
    assert split_cards("") == []
    assert split_cards(None) == []

def test_extract_and_strip_mermaid_are_complementary():
    text = "before\n\n```mermaid\ngraph TD\n```\n\nafter"
    assert extract_mermaid(text) == "graph TD"
    assert "mermaid" not in strip_mermaid(text)

def test_card_wraps_header_and_body():
    out = card("Title", "body")
    assert '<li class="card">' in out
    assert "Title" in out and "body" in out

# A minimal card-family analysis, standing in for a real one.
def _theme(**over):
    base = dict(
        title_suffix="demo", eyebrow="Demo", accent="#000", accent_soft="#eee",
        hero_from="#111", hero_to="#222", eyebrow_color="#333", eyebrow_bar="#444",
        sub_color="#555", card_top_from="#666",
        subtitle=lambda sh: "sub", footer=lambda sh: "foot",
        md_preamble=lambda sh: "")
    base.update(over)
    return Theme(**base)

class _Analysis:
    SECTIONS = [Section("01", "Only", "note", "rail", 400, "body_md")]
    THEME = _theme()

def test_render_html_builds_a_page_from_sections_and_theme():
    out = render_html(_Analysis, "repo", {"body_md": "### A\ntext"})
    assert "<title>repo: demo</title>" in out
    assert "Only" in out and "foot" in out
    assert ".rail.rail .card { flex: 0 0 400px; width: 400px; }" in out

def test_render_html_escapes_the_page_name():
    out = render_html(_Analysis, "<script>x</script>", {"body_md": "### A\nt"})
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out

def test_render_markdown_emits_a_heading_per_section():
    out = render_markdown(_Analysis, "repo", {"body_md": "### A\ntext"})
    assert out.startswith("# repo: demo\n")
    assert "## Only" in out

def test_when_empty_omit_drops_the_section():
    class A(_Analysis):
        SECTIONS = [Section("01", "Gone", "n", "r", 400, "missing", when_empty="omit")]
    assert "Gone" not in render_html(A, "repo", {})
    assert "Gone" not in render_markdown(A, "repo", {})

def test_when_empty_skip_note_renders_a_head_without_a_rail():
    class A(_Analysis):
        SECTIONS = [Section("01", "Skipped", "n", "r", 400, "missing",
                            when_empty="skip-note", skip_note=lambda sh: "nothing found")]
    out = render_html(A, "repo", {})
    assert "nothing found" in out
    assert '<ul class="rail' not in out

def test_a_custom_renderer_wins_over_the_card_engine():
    class Bespoke:
        render_html = staticmethod(lambda name, shared: "<html>custom</html>")
        render_markdown = staticmethod(lambda name, shared: "# custom")
    assert render_html(Bespoke, "repo", {}) == "<html>custom</html>"
    assert render_markdown(Bespoke, "repo", {}) == "# custom"

def test_section_intro_comes_from_the_overview():
    shared = {"body_md": "### A\nt", "overview": {"intros": {"Only": "the intro"}}}
    assert "the intro" in render_html(_Analysis, "repo", shared)
````

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_core_render.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'crack.core.render'`

- [ ] **Step 3: Copy the engine from the sibling**

Run:

```bash
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/core/render.py src/crack/core/render.py
```

357 lines, copied verbatim. Do not edit it. Its only import beyond the standard library is `from markdown_it import MarkdownIt`, already a dependency.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 169 passed.

If `test_render_html_escapes_the_page_name` fails, stop and report it rather than patching the engine. Escaping the repo name is a security property this project has been bitten by before (see `.full-review/02a-security.md`), and a failure means the copied engine is not the file the sibling's own tests cover.

- [ ] **Step 5: Commit**

```bash
git add src/crack/core/render.py tests/test_core_render.py
git commit -m "feat(core): add the card-family render engine"
```

---

### Task 4: `OverviewNode` and the overview writer

**Files:**

- Create: `src/crack/core/overview.py`, `src/crack/core/nodes.py`
- Modify: `src/crack/core/__init__.py`
- Test: `tests/test_overview.py`

**Interfaces:**

- Consumes: `crack.core.call_llm`.
- Produces:
  - `crack.core.overview.write_overview(name, what, sections, facts="") -> {"welcome": str, "intros": {title: str}}` where `sections` is a list of `(title, gist)` pairs.
  - `crack.core.nodes.OverviewNode(spec, max_retries=2, wait=2)`, a PocketFlow `Node`. `spec(shared)` returns `{"name", "what", "sections", "facts"}`. Writes `shared["overview"]`. Its `exec_fallback` returns `{"welcome": "", "intros": {}}` so a failed call leaves the page without intro copy rather than killing the run.
- Both re-exported as `crack.core.write_overview` and `crack.core.OverviewNode`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_overview.py`:

```python
import pytest

from crack.core import OverviewNode, write_overview

SECTIONS = [("The pipeline", "the six layers"), ("The code", "the odd bits")]

REPLY = """## Welcome
toy_repo is a small Django service.

## The pipeline
Four routes fan into eleven handlers.

## The code
Only routing is unusual.
"""

def test_write_overview_splits_the_reply_into_welcome_and_intros(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm", lambda prompt: REPLY)
    out = write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert out["welcome"] == "toy_repo is a small Django service."
    assert out["intros"]["The pipeline"] == "Four routes fan into eleven handlers."
    assert out["intros"]["The code"] == "Only routing is unusual."

def test_write_overview_falls_back_to_the_gist_for_a_missing_header(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm",
                        lambda prompt: "## Welcome\nhi\n\n## The pipeline\nthere")
    out = write_overview("toy_repo", "a backend", SECTIONS)
    assert out["intros"]["The code"] == "the odd bits"

def test_write_overview_prompt_carries_the_name_facts_and_headers(monkeypatch):
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return REPLY

    monkeypatch.setattr("crack.core.overview.call_llm", capture)
    write_overview("toy_repo", "a backend", SECTIONS, facts="4 routes")
    assert "toy_repo" in seen["p"]
    assert "4 routes" in seen["p"]
    assert "## The pipeline" in seen["p"]

def test_overview_node_stores_the_result_on_shared(monkeypatch):
    monkeypatch.setattr("crack.core.overview.call_llm", lambda prompt: REPLY)
    shared = {"repo_path": "/tmp/toy_repo"}
    node = OverviewNode(lambda sh: {"name": "toy_repo", "what": "a backend",
                                    "sections": SECTIONS, "facts": ""})
    node.run(shared)
    assert shared["overview"]["welcome"] == "toy_repo is a small Django service."

def test_overview_node_leaves_empty_copy_when_the_call_keeps_failing(monkeypatch):
    def boom(prompt):
        raise RuntimeError("no api key")
    monkeypatch.setattr("crack.core.overview.call_llm", boom)
    shared = {}
    node = OverviewNode(lambda sh: {"name": "n", "what": "w", "sections": SECTIONS},
                        max_retries=1, wait=0)
    node.run(shared)
    assert shared["overview"] == {"welcome": "", "intros": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_overview.py -q`
Expected: FAIL, `ImportError: cannot import name 'OverviewNode' from 'crack.core'`

- [ ] **Step 3: Copy both files from the sibling**

Run:

```bash
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/core/overview.py src/crack/core/overview.py
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/core/nodes.py src/crack/core/nodes.py
```

`overview.py` is 88 lines, `nodes.py` is 32. Both copy verbatim; their imports (`from .call_llm import call_llm`, `from .overview import write_overview`) are already correct for coderay's layout.

- [ ] **Step 4: Re-export both**

In `src/crack/core/__init__.py`, add after the `.env` import:

```python
from .nodes import OverviewNode  # noqa: F401
from .overview import write_overview  # noqa: F401
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 174 passed.

- [ ] **Step 6: Commit**

```bash
git add src/crack/core/overview.py src/crack/core/nodes.py src/crack/core/__init__.py tests/test_overview.py
git commit -m "feat(core): add OverviewNode and the page-overview writer"
```

---

### Task 5: `run_analysis`

**Files:**

- Modify: `src/crack/core/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**

- Consumes: `crack.core.env.env_defaults`, `crack.core.render.render_html`, `crack.core.render.render_markdown`.
- Produces: `crack.core.runner.run_analysis(analysis, args) -> str` (the output directory). It:
  1. resolves `out_dir` from `args.out`, else `<cwd>/output/<repo-name>-<analysis.NAME>`;
  2. creates it before the flow runs, because some analyses write extra files into it mid-run;
  3. calls `analysis.init_shared(args)`;
  4. runs `analysis.build_flow()` inside `env_defaults(getattr(analysis, "ENV_DEFAULTS", {}))`;
  5. writes `index.md` and `index.html` through `crack.core.render`;
  6. prints where it wrote, and returns `out_dir`.

`init_shared` takes only `args`, matching `tour`'s signature, not the sibling's `(args, out_dir)`.

There is deliberately no failure-state dump here. `tour` has one; giving the ported analyses the same is part of coderay-dr8, not this plan.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner.py`:

```python
import os

import pytest

from crack.core.render import Section, Theme
from crack.core.runner import run_analysis

class _Args:
    def __init__(self, repo_path, out=None):
        self.repo_path = repo_path
        self.out = out

def _fake_analysis(env_defaults_dict=None, record=None):
    class Flow:
        def run(self, shared):
            shared["body_md"] = "### A\ntext"
            if record is not None:
                record["max_tokens"] = os.environ.get("LLM_MAX_OUTPUT_TOKENS")

    class Analysis:
        NAME = "demo"
        SECTIONS = [Section("01", "Only", "note", "rail", 400, "body_md")]
        THEME = Theme(
            title_suffix="demo", eyebrow="Demo", accent="#000", accent_soft="#eee",
            hero_from="#111", hero_to="#222", eyebrow_color="#333", eyebrow_bar="#444",
            sub_color="#555", card_top_from="#666",
            subtitle=lambda sh: "sub", footer=lambda sh: "foot",
            md_preamble=lambda sh: "")
        init_shared = staticmethod(lambda args: {"repo_path": args.repo_path})
        build_flow = staticmethod(Flow)

    if env_defaults_dict:
        Analysis.ENV_DEFAULTS = env_defaults_dict
    return Analysis

def test_run_analysis_writes_both_index_files(tmp_path):
    out = tmp_path / "out"
    run_analysis(_fake_analysis(), _Args(str(tmp_path), out=str(out)))
    assert (out / "index.html").read_text().startswith("<!doctype html>")
    assert (out / "index.md").read_text().startswith("# ")

def test_run_analysis_defaults_the_output_dir_to_cwd_output(tmp_path, monkeypatch):
    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    out = run_analysis(_fake_analysis(), _Args(str(repo)))
    assert out == os.path.join(str(tmp_path), "output", "toy_repo-demo")
    assert os.path.isfile(os.path.join(out, "index.html"))

def test_run_analysis_applies_env_defaults_during_the_flow(tmp_path):
    record = {}
    analysis = _fake_analysis({"LLM_MAX_OUTPUT_TOKENS": "32768"}, record)
    run_analysis(analysis, _Args(str(tmp_path), out=str(tmp_path / "o")))
    assert record["max_tokens"] == "32768"
    assert "LLM_MAX_OUTPUT_TOKENS" not in os.environ

def test_run_analysis_creates_the_output_dir_before_the_flow_runs(tmp_path):
    out = tmp_path / "o"
    seen = {}

    class Flow:
        def run(self, shared):
            seen["existed"] = out.is_dir()
            shared["body_md"] = "### A\nt"

    analysis = _fake_analysis()
    analysis.build_flow = staticmethod(Flow)
    run_analysis(analysis, _Args(str(tmp_path), out=str(out)))
    assert seen["existed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_runner.py -q`
Expected: FAIL, `ImportError: cannot import name 'run_analysis' from 'crack.core.runner'`

- [ ] **Step 3: Write the implementation**

In `src/crack/core/runner.py`, add the imports at the top and the function below `run_flow`:

```python
"""Runs a pipeline flow against a shared state dict, common to any analysis."""
import os

from .env import env_defaults
from .render import render_html, render_markdown
```

```python
def default_output_dir(repo_path, analysis_name):
    """Anchored on the current working directory, not this file's location, so
    output lands in the same place whether crack runs from an editable checkout
    or as an installed tool."""
    name = os.path.basename(os.path.abspath(repo_path))
    return os.path.join(os.getcwd(), "output", f"{name}-{analysis_name}")

def run_analysis(analysis, args):
    """Run one analysis and write its index.md and index.html. Returns out_dir.

    The output directory is created before the flow runs, because an analysis
    may write extra files into it during the run."""
    out_dir = args.out or default_output_dir(args.repo_path, analysis.NAME)
    os.makedirs(out_dir, exist_ok=True)

    name = os.path.basename(os.path.abspath(args.repo_path))
    shared = analysis.init_shared(args)
    with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
        analysis.build_flow().run(shared)

    with open(os.path.join(out_dir, "index.md"), "w") as fh:
        fh.write(render_markdown(analysis, name, shared))
    with open(os.path.join(out_dir, "index.html"), "w") as fh:
        fh.write(render_html(analysis, name, shared))

    print(f"\nWrote {analysis.NAME} to {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser")
    return out_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 178 passed.

- [ ] **Step 5: Commit**

```bash
git add src/crack/core/runner.py tests/test_runner.py
git commit -m "feat(core): add run_analysis for the ported card-family analyses"
```

---

### Task 6: the backend crawl

**Files:**

- Create: `src/crack/analyses/backend/__init__.py` (placeholder for now), `src/crack/analyses/backend/backend_crawl.py`
- Test: `tests/test_backend_crawl.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `classify(rel) -> str | None`, one of `route`, `middleware`, `handler`, `service`, `database`, `response`, or `None`.
  - `build_bundle(repo, max_chars=650_000, per_layer_sample=18) -> (bundle_text, {"counts": dict, "included": int})`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backend_crawl.py`:

```python
import os

import pytest

from crack.analyses.backend import backend_crawl as bc

@pytest.mark.parametrize("rel,layer", [
    ("app/urls.py", "route"),
    ("api/routes/user.ts", "route"),
    ("pages/api/login.ts", "route"),
    ("app/middleware.py", "middleware"),
    ("app/decorators.py", "middleware"),
    ("app/views/message.py", "handler"),
    ("app/controllers/user.rb", "handler"),
    ("app/actions/send.py", "service"),
    ("app/services/billing.py", "service"),
    ("app/models/user.py", "database"),
    ("app/models.py", "database"),
    ("app/serializers/user.py", "response"),
])
def test_classify_maps_a_path_to_its_layer(rel, layer):
    assert bc.classify(rel) == layer

@pytest.mark.parametrize("rel", [
    "README.md", "app/style.css", "app/views/message.test.py",
    "app/views/user.spec.ts", "app/util.py",
])
def test_classify_returns_none_for_a_non_layer_file(rel):
    assert bc.classify(rel) is None

def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return str(tmp_path)

def test_build_bundle_counts_every_layer_and_includes_the_spine(tmp_path):
    repo = _repo(tmp_path, {
        "app/urls.py": "urlpatterns = []\n",
        "app/middleware.py": "class Mw: pass\n",
        "app/views/message.py": "def send(): pass\n",
        "app/models.py": "class User: pass\n",
    })
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {"route": 1, "middleware": 1, "handler": 1, "database": 1}
    assert "LAYER FILE COUNTS" in bundle
    assert "LAYER ROUTE: app/urls.py" in bundle
    assert "urlpatterns = []" in bundle
    assert stats["included"] == 4

def test_build_bundle_skips_ignored_directories(tmp_path):
    repo = _repo(tmp_path, {
        "app/urls.py": "ok\n",
        "tests/urls.py": "ignored\n",
        "node_modules/pkg/routes/a.js": "ignored\n",
        "migrations/urls.py": "ignored\n",
    })
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"]["route"] == 1
    assert "ignored" not in bundle

def test_build_bundle_returns_an_empty_bundle_for_a_repo_with_no_backend(tmp_path):
    repo = _repo(tmp_path, {"README.md": "# hi\n", "index.html": "<p>x</p>\n"})
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {}
    assert stats["included"] == 0

def test_build_bundle_caps_total_size(tmp_path):
    repo = _repo(tmp_path, {f"app/routes/r{i}.py": "x" * 2000 for i in range(20)})
    bundle, stats = bc.build_bundle(repo, max_chars=6000)
    assert len(bundle) <= 6000
    assert stats["counts"]["route"] == 20
    assert stats["included"] < 20

def test_build_bundle_samples_handlers_and_prefers_core_names(tmp_path):
    files = {f"app/views/zz{i}.py": "pass\n" for i in range(20)}
    files["app/views/message.py"] = "def send(): pass\n"
    repo = _repo(tmp_path, files)
    bundle, stats = bc.build_bundle(repo, per_layer_sample=2)
    assert stats["counts"]["handler"] == 21
    assert "app/views/message.py" in bundle
    assert stats["included"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_backend_crawl.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'crack.analyses.backend'`

- [ ] **Step 3: Create the package and copy the crawl**

Run:

```bash
mkdir -p src/crack/analyses/backend
printf '"""Read a backend as the six layers every request flows through."""\n' > src/crack/analyses/backend/__init__.py
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/analyses/backend/backend_crawl.py src/crack/analyses/backend/backend_crawl.py
```

114 lines, copied verbatim, standard library only. Task 8 replaces the placeholder `__init__.py`.

- [ ] **Step 4: Register the package so it installs**

In `pyproject.toml`, add `"crack.analyses.backend",` to the `[tool.setuptools] packages` list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 200 passed.

`classify` normalizes with `rel.replace(os.sep, '/')`. That is correct and needs no change: it is only ever called with `os.path.relpath` output, so a backslash path arrives only on Windows, where `os.sep` is a backslash. On POSIX a backslash is a legal filename character rather than a separator, so leaving it alone is right. Do not add a test asserting that a backslash path classifies on POSIX; it would encode behavior that cannot occur.

- [ ] **Step 6: Commit**

```bash
git add src/crack/analyses/backend/ pyproject.toml tests/test_backend_crawl.py
git commit -m "feat(backend): add the six-layer backend crawl"
```

---

### Task 7: the backend nodes

**Files:**

- Create: `src/crack/analyses/backend/nodes.py`, `src/crack/analyses/backend/prompts/{pipeline.md,layer-code.md,trace.md}`
- Modify: `pyproject.toml`
- Test: `tests/test_backend_nodes.py`

**Interfaces:**

- Consumes: `crack.core.call_llm`, `read_prompt`, `fill`, `extract_mermaid`; `crack.analyses.backend.backend_crawl`.
- Produces: `BuildBundle`, `Pipeline`, `LayerCode`, `Trace`, all PocketFlow `Node`s. They set these keys on `shared`: `codebase`, `layer_counts` (BuildBundle); `pipeline_md`, `pipeline_diagram` (Pipeline); `layercode_md` (LayerCode); `trace_md`, `trace_endpoint` (Trace).

- [ ] **Step 1: Write the failing test**

Create `tests/test_backend_nodes.py`:

````python
import pytest

from crack.analyses.backend import nodes as n

CARDS = "### Route\nbody\n\n### Handler\nbody\n"

def test_build_bundle_populates_codebase_and_counts(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "urls.py").write_text("urlpatterns = []\n")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert "urlpatterns" in shared["codebase"]
    assert shared["layer_counts"]["route"] == 1

def test_build_bundle_does_not_reject_a_repo_with_no_backend(tmp_path):
    """Known limitation, tracked as coderay-q2r.8.

    BuildBundle.post asserts `bundle.strip()` to reject a repo with no
    server-side backend, but build_bundle always prepends a six-line layer-count
    header, so the bundle is never empty and the guard never fires. The run
    proceeds and spends three LLM calls on a bundle of "0 files" lines.
    Inherited from the port source and deliberately not fixed here, because
    nodes.py is a near-verbatim copy. When upstream fixes it this test fails,
    which is the signal to re-port and invert it.
    """
    (tmp_path / "README.md").write_text("# hi\n")
    shared = {"repo_path": str(tmp_path)}
    n.BuildBundle().run(shared)
    assert shared["layer_counts"] == {}
    assert "route: 0 files" in shared["codebase"]

def test_pipeline_stores_markdown_and_the_diagram(monkeypatch):
    reply = "```mermaid\nflowchart LR\n  a --> b\n```\n\n" + CARDS
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Pipeline().run(shared)
    assert shared["pipeline_md"].startswith("```mermaid")
    assert shared["pipeline_diagram"] == "flowchart LR\n  a --> b"

def test_pipeline_leaves_the_diagram_empty_when_none_is_drawn(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.Pipeline().run(shared)
    assert shared["pipeline_diagram"] == ""

def test_pipeline_retries_a_reply_with_no_cards(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return "no cards here" if len(calls) < 3 else CARDS

    monkeypatch.setattr(n, "call_llm", reply)
    node = n.Pipeline()
    node.wait = 0
    shared = {"codebase": "x"}
    node.run(shared)
    assert len(calls) == 3
    assert shared["pipeline_md"] == CARDS.strip()

def test_layer_code_stores_markdown(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.LayerCode().run(shared)
    assert shared["layercode_md"] == CARDS.strip()

def test_trace_pulls_the_endpoint_out_of_the_reply(monkeypatch):
    reply = "**Endpoint:** POST /json/messages\n\n" + CARDS
    monkeypatch.setattr(n, "call_llm", lambda prompt: reply)
    shared = {"codebase": "x"}
    n.Trace().run(shared)
    assert shared["trace_endpoint"] == "POST /json/messages"

def test_trace_tolerates_a_reply_with_no_endpoint_line(monkeypatch):
    monkeypatch.setattr(n, "call_llm", lambda prompt: CARDS)
    shared = {"codebase": "x"}
    n.Trace().run(shared)
    assert shared["trace_endpoint"] == ""

@pytest.mark.parametrize("name", ["pipeline.md", "layer-code.md", "trace.md"])
def test_every_prompt_loads_and_has_a_codebase_slot(name):
    text = n.load_prompt(name)
    assert "{codebase}" in text

def test_the_codebase_slot_is_filled(monkeypatch):
    seen = {}

    def capture(prompt):
        seen["p"] = prompt
        return CARDS

    monkeypatch.setattr(n, "call_llm", capture)
    n.Pipeline().run({"codebase": "MARKER_TEXT"})
    assert "MARKER_TEXT" in seen["p"]
    assert "{codebase}" not in seen["p"]
````

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_backend_nodes.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'crack.analyses.backend.nodes'`

- [ ] **Step 3: Copy the nodes and prompts**

Run:

```bash
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/analyses/backend/nodes.py src/crack/analyses/backend/nodes.py
cp -R ~/code/Crack-Any-Codebase-with-AI/src/crack/analyses/backend/prompts src/crack/analyses/backend/prompts
```

- [ ] **Step 4: Switch prompt loading to importlib.resources**

The copied `nodes.py` builds `PROMPTS_DIR` with `os.path.join`, which coderay's `read_prompt` cannot consume. Replace the two lines:

```python
import os
import re
```

```python
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')
```

with:

```python
import re
from importlib import resources
```

```python
PROMPTS_DIR = resources.files("crack.analyses.backend") / "prompts"
```

`os` is no longer used in the file after this change; confirm with `grep -n 'os\.' src/crack/analyses/backend/nodes.py` returning nothing before removing the import.

- [ ] **Step 5: Ship the prompts in the package**

In `pyproject.toml`, under `[tool.setuptools.package-data]`, add:

```toml
"crack.analyses.backend" = ["prompts/*.md"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 212 passed.

- [ ] **Step 7: Commit**

```bash
git add src/crack/analyses/backend/nodes.py src/crack/analyses/backend/prompts/ pyproject.toml tests/test_backend_nodes.py
git commit -m "feat(backend): add the pipeline, layer-code, and trace nodes"
```

---

### Task 8: wire up the backend analysis and its golden test

**Files:**

- Modify: `src/crack/analyses/backend/__init__.py`, `src/crack/analyses/__init__.py`
- Create: `scripts/regen_golden.py`, `tests/fixtures/golden/backend/{shared.json,index.html,index.md}`
- Test: `tests/test_backend.py`, `tests/test_golden.py`

**Interfaces:**

- Consumes: everything from Tasks 1-7.
- Produces: the `backend` analysis module satisfying coderay's interface: `NAME = "backend"`, `SECTIONS`, `THEME`, `ENV_DEFAULTS`, `build_flow()`, `add_arguments(parser)`, `init_shared(args)`, `run(args)`, `overview_spec(shared)`. Registered as `ANALYSES["backend"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backend.py`:

```python
import argparse
import os

import pytest

from crack.analyses import ANALYSES
from crack.analyses import backend

def test_backend_is_registered():
    assert ANALYSES["backend"] is backend
    assert backend.NAME == "backend"

def test_backend_satisfies_the_analysis_interface():
    for attr in ("NAME", "build_flow", "add_arguments", "init_shared", "run"):
        assert hasattr(backend, attr), attr

def test_backend_declares_the_card_family_contract():
    assert len(backend.SECTIONS) == 3
    assert [s.key for s in backend.SECTIONS] == ["pipeline_md", "layercode_md", "trace_md"]
    assert [s.number for s in backend.SECTIONS] == ["01", "02", "03"]
    assert backend.THEME.title_suffix == "backend"

def test_backend_raises_more_output_tokens():
    assert backend.ENV_DEFAULTS == {"LLM_MAX_OUTPUT_TOKENS": "32768"}

def test_add_arguments_adds_no_flags_of_its_own():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default=None)
    before = {a.dest for a in parser._actions}
    backend.add_arguments(parser)
    assert {a.dest for a in parser._actions} == before

def test_init_shared_carries_the_repo_path():
    args = argparse.Namespace(repo_path="/tmp/toy_repo", out=None)
    assert backend.init_shared(args) == {"repo_path": "/tmp/toy_repo"}

def test_build_flow_starts_at_build_bundle():
    from crack.analyses.backend.nodes import BuildBundle
    assert isinstance(backend.build_flow().start_node, BuildBundle)

def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x")
    with pytest.raises(SystemExit, match="is not a directory"):
        backend.run(argparse.Namespace(repo_path=str(f), out=None))

def test_overview_spec_names_the_three_sections():
    spec = backend.overview_spec({"repo_path": "/tmp/toy_repo", "layer_counts": {"route": 4}})
    assert spec["name"] == "toy_repo"
    assert [t for t, _ in spec["sections"]] == ["The pipeline", "The code", "The trace"]
    assert "route 4" in spec["facts"]


def test_overview_spec_name_matches_the_name_the_page_is_rendered_with(tmp_path, monkeypatch):
    """The overview prompt and the page title must name the same repo.

    run_analysis hands the renderer repo_name_of(args.repo_path) as the page
    title. If overview_spec computed the name differently, the LLM-written copy
    would name a different repo than the heading above it. A relative path is
    the case that exposes a divergence.
    """
    from crack.core.runner import repo_name_of

    repo = tmp_path / "toy_repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    spec = backend.overview_spec({"repo_path": ".", "layer_counts": {}})
    assert spec["name"] == repo_name_of(".") == "toy_repo"
    # "." is the shape that separates the two implementations: a naive
    # os.path.basename(repo_path) returns "." here, not the directory name.
    assert spec["name"] != os.path.basename(".")
```

Create `tests/test_golden.py`:

```python
"""The ported analyses must reproduce their source's output byte for byte.

Regenerate a fixture with scripts/regen_golden.py after a deliberate change.
"""
import json
import pathlib

import pytest

from crack.analyses import ANALYSES
from crack.core import render

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden"

@pytest.mark.parametrize("name", ["backend"])
def test_golden_html(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text())
    assert render.render_html(ANALYSES[name], "toy_repo", shared) == (d / "index.html").read_text()

@pytest.mark.parametrize("name", ["backend"])
def test_golden_markdown(name):
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text())
    assert render.render_markdown(ANALYSES[name], "toy_repo", shared) == (d / "index.md").read_text()

@pytest.mark.parametrize("name", ["backend"])
def test_golden_html_escapes_injected_markup(name):
    """Every fixture carries injected markup in two places on purpose: a card
    header, and the mermaid diagram source.

    The diagram is the one that bit the port source (see its commit 725b01e).
    A diagram containing </pre><script> closed the pre element and executed
    when the page was opened. Mermaid reads the element's textContent, which
    the browser decodes back, so escaping the source is safe and reversible.
    """
    d = GOLDEN / name
    html = (d / "index.html").read_text()
    assert "<script>" not in html.split("</head>", 1)[1]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/pre&gt;&lt;script&gt;" in html


@pytest.mark.parametrize("name", ["backend"])
def test_render_escapes_the_diagram_it_is_handed(name):
    """The golden files are static; this re-renders to catch a live regression."""
    d = GOLDEN / name
    shared = json.loads((d / "shared.json").read_text())
    assert "</pre><script>" in shared["pipeline_diagram"], "fixture lost its payload"
    html = render.render_html(ANALYSES[name], "toy_repo", shared)
    assert "</pre><script>" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_backend.py tests/test_golden.py -q`
Expected: FAIL, `ImportError: cannot import name 'backend' from 'crack.analyses'`

- [ ] **Step 3: Write the analysis module**

Copy the sibling's version as the starting point:

```bash
cp ~/code/Crack-Any-Codebase-with-AI/src/crack/analyses/backend/__init__.py src/crack/analyses/backend/__init__.py
```

Then make it fit coderay's interface. Change the import block from:

```python
from crack.core import OverviewNode
from crack.core.render import Section, Theme
from .nodes import BuildBundle, Pipeline, LayerCode, Trace
```

to:

```python
from crack.core import OverviewNode
from crack.core.render import Section, Theme, esc
from crack.core.runner import repo_name_of, run_analysis
from .nodes import BuildBundle, Pipeline, LayerCode, Trace
```

Then delete the now-unused `import os` from the top of the file and add `import sys` (`run()` below needs it).

**Also in this step, add `repo_name_of` to `src/crack/core/runner.py`** and route the two existing
call sites through it, replacing the inline `os.path.basename(os.path.abspath(...))` in both
`default_output_dir` and `run_analysis`:

```python
def repo_name_of(repo_path):
    """The repo's directory name, used for the output folder and the page title.

    One helper so the name the overview prompt is given always matches the name
    rendered on the page. Resolving to an absolute path first keeps a relative
    repo_path (".", "../thing/") from yielding a useless name."""
    return os.path.basename(os.path.abspath(repo_path))
```

`overview_spec` must then use `repo_name_of(shared["repo_path"])` rather than computing the
basename itself. This matters: `run_analysis` passes its own `repo_name_of(...)` result to the
renderer as the page title, so a second, different computation inside `overview_spec` makes the
LLM-written overview copy name a different repo than the page heading it sits under. The port
source hit exactly this and fixed it in commit 505d7e2, "use repo_name_of in overview_spec so the
prompt matches the page". It also removes the duplication flagged as a Minor when `run_analysis`
landed.

Change `init_shared` from the sibling's two-argument form to coderay's:

```python
def init_shared(args):
    return {"repo_path": args.repo_path}
```

and append the two functions the sibling's generic runner made unnecessary:

```python
def add_arguments(parser) -> None:
    """The backend analysis takes no flags beyond the common repo_path/--out."""

def run(args) -> None:
    # Exit code 1, no usage line, matching tour's run(): run(args) has no
    # parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")
    run_analysis(sys.modules[__name__], args)
```



- [ ] **Step 4: Register it**

Replace `src/crack/analyses/__init__.py` with:

```python
"""Registry of available analyses: name -> module implementing the analysis
interface (NAME, build_flow, add_arguments, init_shared, run)."""
from crack.analyses import backend, tour

ANALYSES = {a.NAME: a for a in (tour, backend)}
```

`tour` stays first so `crack --help` lists it first.

- [ ] **Step 5: Write the golden regeneration script**

Create `scripts/regen_golden.py`:

```python
#!/usr/bin/env python3
"""Regenerate a golden render fixture from the sibling port source.

The golden files under tests/fixtures/golden/<analysis>/ pin the exact HTML and
markdown a ported analysis produces for a fixed `shared` dict. They are
generated from the port source of record, not from crack itself, so the test
proves the port stayed faithful rather than proving crack agrees with itself.

Use it when a deliberate change to the card engine or to an analysis's THEME or
SECTIONS makes a golden test fail. Never use it to silence an unexplained
failure -- diff the output first and know why it moved.

    scripts/regen_golden.py backend
    scripts/regen_golden.py backend --sibling ~/code/Crack-Any-Codebase-with-AI

The sibling checkout must be on the pinned port-source commit; the script
refuses to run otherwise. See docs/superpowers/specs/2026-09-01-analysis-port-design.md.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

PORT_SOURCE_COMMIT = "34f0ad2a7044284555911590ca3773c92e1244ac"
DEFAULT_SIBLING = pathlib.Path.home() / "code" / "Crack-Any-Codebase-with-AI"
GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis", help="the analysis to regenerate, e.g. backend")
    ap.add_argument("--sibling", type=pathlib.Path, default=DEFAULT_SIBLING,
                    help=f"port source checkout (default: {DEFAULT_SIBLING})")
    ap.add_argument("--allow-any-commit", action="store_true",
                    help="skip the pinned-commit check (you must say why in the commit message)")
    args = ap.parse_args()

    out_dir = GOLDEN / args.analysis
    shared_path = out_dir / "shared.json"
    if not shared_path.is_file():
        sys.exit(f"no fixture input at {shared_path}")

    head = subprocess.run(["git", "-C", str(args.sibling), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != PORT_SOURCE_COMMIT and not args.allow_any_commit:
        sys.exit(f"{args.sibling} is at {head or '(not a git checkout)'}, "
                 f"expected the pinned port source {PORT_SOURCE_COMMIT}.\n"
                 f"Check it out, or pass --allow-any-commit deliberately.")

    sys.path.insert(0, str(args.sibling / "src"))
    from crack.analyses import load           # the sibling's registry, not ours
    from crack.core import render

    analysis = load(args.analysis)
    shared = json.loads(shared_path.read_text())
    (out_dir / "index.html").write_text(render.render_html(analysis, "toy_repo", shared))
    (out_dir / "index.md").write_text(render.render_markdown(analysis, "toy_repo", shared))
    print(f"wrote {out_dir}/index.html and {out_dir}/index.md from {args.sibling} @ {head[:7]}")

if __name__ == "__main__":
    main()
```

Make it executable: `chmod +x scripts/regen_golden.py`

- [ ] **Step 6: Create the fixture input and generate the golden files**

Create `tests/fixtures/golden/backend/shared.json`:

````json
{
  "repo_path": "/tmp/toy_repo",
  "layer_counts": {
    "route": 4,
    "middleware": 2,
    "handler": 11,
    "service": 5,
    "database": 3,
    "response": 1
  },
  "pipeline_diagram": "flowchart LR\n  route --> mw\n  </pre><script>alert('xss')</script>",
  "pipeline_md": "```mermaid\nflowchart LR\n  route --> mw\n  </pre><script>alert('xss')</script>\n```\n\n### Route <script>alert(1)</script>\n\nOne `urls.py` maps **4** paths. See `app/urls.py:12`.\n\n### Middleware\n\nTwo layers, both custom:\n\n- auth\n- rate limiting\n\n### Handler\n\n11 views under `app/views/`.\n",
  "layercode_md": "### Route \u2014 novel\n\nA `rest_path` wrapper folds method dispatch into the URL table.\n\n```python\ndef rest_path(route, **handlers):\n    return path(route, rest_dispatch(**handlers))\n```\n\n### Middleware \u2014 standard\n\nStock Django middleware, nothing to read.\n",
  "trace_md": "**Endpoint:** POST /json/messages\n\n### 1. Route\n\n`app/urls.py:44` matches the path.\n\n### 2. Handler\n\n`app/views/message.py:88` validates, then calls the service.\n\n| field | required |\n| --- | --- |\n| `content` | yes |\n",
  "trace_endpoint": "POST /json/messages",
  "overview": {
    "welcome": "toy_repo is a small Django service with a hand-rolled REST dispatcher and a two-layer middleware stack.",
    "intros": {
      "The pipeline": "Four routes fan into eleven handlers; the service layer is thin.",
      "The code": "Only the routing layer is unusual, and it is one wrapper function.",
      "The trace": "One message write, committed before the response returns."
    }
  }
}
````

This exercises every branch the renderer has: a hero diagram, a card header carrying injected markup, a fenced code block, a markdown table, a bullet list, and a full overview with per-section intros.

Then run:

```bash
scripts/regen_golden.py backend
```

Expected: `wrote tests/fixtures/golden/backend/index.html and .../index.md from ... @ 34f0ad2`. The HTML should be 248 lines and the markdown 59.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 226 passed.

- [ ] **Step 8: Verify the CLI end to end**

Run:

```bash
uv run crack --help
uv run crack backend --help
uv run crack backend /nonexistent-path; echo "exit=$?"
```

Expected: `--help` lists both `tour` and `backend`; `backend --help` shows `repo_path` and `--out`; the bad path prints `/nonexistent-path is not a directory` and `exit=1`.

- [ ] **Step 9: Commit**

```bash
git add src/crack/analyses/backend/__init__.py src/crack/analyses/__init__.py \
        scripts/regen_golden.py tests/fixtures/golden/ tests/test_backend.py tests/test_golden.py
git commit -m "feat(backend): register the backend analysis with a golden render test"
```

---

### Task 9: documentation

**Files:**

- Modify: `README.md`, `CLAUDE.md`, `AGENTS.md`
- Test: `tests/test_package_skeleton.py`

**Interfaces:**

- Consumes: the finished `backend` analysis.
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_package_skeleton.py`:

```python
def test_every_registered_analysis_is_documented():
    import pathlib
    from crack.analyses import ANALYSES
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text()
    for name in ANALYSES:
        assert f"crack {name}" in readme, f"README.md does not document `crack {name}`"

def test_every_registered_analysis_ships_its_package_data():
    import pathlib
    import tomllib
    from crack.analyses import ANALYSES
    root = pathlib.Path(__file__).parent.parent
    cfg = tomllib.loads((root / "pyproject.toml").read_text())
    packages = cfg["tool"]["setuptools"]["packages"]
    for name in ANALYSES:
        pkg = f"crack.analyses.{name.replace('-', '_')}"
        assert pkg in packages, f"{pkg} missing from [tool.setuptools] packages"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_package_skeleton.py -q`
Expected: FAIL, `AssertionError: README.md does not document 'crack backend'`

- [ ] **Step 3: Update the docs**

In `README.md`, wherever `crack tour path/to/repo` is shown as the invocation, present the two analyses as a list. Add a short section describing `backend`: it reads a server-side backend as six layers (route, middleware, handler, service, database, response), and produces three views -- the pipeline with a file count per layer, the code at the layers built unusually, and a trace of one request through all six. Note that it expects a server-side backend (Django, Express, Rails, FastAPI) and asserts out with a clear message on a repo that has none.

In `CLAUDE.md` and `AGENTS.md`, under "Architecture Overview", note that `crack` now dispatches to more than one analysis: `tour` (the five-node chapter pipeline, unchanged) and `backend` (`BuildBundle -> Pipeline -> LayerCode -> Trace -> OverviewNode`). Add to "Conventions & Patterns" that card-family analyses declare `SECTIONS` and `THEME` and are rendered by `crack/core/render.py`, and that an analysis with a page shape that does not fit declares `render_html`/`render_markdown` instead. State the count as it is TODAY (backend alone), not as the epic's end state. Each later port updates this line as it lands. Keep both files in sync; they are independent files, not symlinks.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, 228 passed.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md AGENTS.md tests/test_package_skeleton.py
git commit -m "docs: document the backend analysis and the card-family contract"
```

---

## Done when

- `uv run python -m pytest tests/ -q` passes with roughly 228 tests, up from the 145 baseline.
- `uv run crack backend --help` works, and `crack tour` behaves exactly as before.
- `crack/analyses/tour/` and `crack/cli.py` are untouched: `git diff a7b6df9 --stat -- src/crack/analyses/tour src/crack/cli.py` prints nothing.
- The golden fixture regenerates identically: `scripts/regen_golden.py backend && git diff --exit-code tests/fixtures/golden/`.

## Notes for the follow-up ports

Tasks 1-5 are one-time core work. Architecture, interfaces, and schema each reduce to Tasks 6-9: copy the crawl, copy the nodes, switch prompt loading to `importlib.resources`, adapt `__init__.py` (`init_shared` signature, add `add_arguments` and `run`), register, add a golden fixture, document. Two of them declare `Section` hooks Task 3's engine already supports but backend does not use: `when_empty="omit"` (interfaces), and `when_empty="skip-note"` with `skip_note`/`md_skip_note` (schema). The engine handles both already; the tests in Task 3 cover them.
