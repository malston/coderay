# Crack CLI Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure coderay's single-pipeline `workflow`/`coderay_utils` layout into a `src/crack/` package with a `crack` console script that dispatches to named analysis subcommands (today: `crack tour <repo>`), with no behavior change.

**Architecture:** Move `coderay_utils/*` to `src/crack/core/*` (shared plumbing), move the pipeline (`workflow/nodes.py`, `flow.py`, `prompts/`, `instructions/`, `graph/`) to `src/crack/analyses/tour/*`, and split `workflow/__main__.py` into a thin `cli.py` dispatcher plus `analyses/tour/render.py` (all of today's rendering/dry-run/session-summary logic). Each task is a pure move + import-path update, landing green before the next task starts.

**Tech Stack:** Python 3.10+, setuptools src layout, pytest, uv, pocketflow.

**Spec:** `docs/superpowers/specs/2026-08-31-unified-cli-restructure-design.md`

## Global Constraints

- **No behavior change anywhere in this migration** — every existing test passes unmodified except for import paths (spec's Testing section). If a step would change what a function returns or does, stop and flag it instead of proceeding.
- **Clean break** — no `python -m workflow`, no back-compat shim for the old `coderay <repo>` invocation (spec Goals).
- **GitHub repo rename is deferred.** Do not rename the repo, and do not assume the new clone URL anywhere in code, docs, or CI. Confirmed with Mark 2026-08-31: hold off.
- **PR + Copilot review loop**, same as PR #23 — this lands as a reviewed PR, not a direct merge to `main`. Confirmed with Mark 2026-08-31.
- **Config/cache paths rename `coderay` → `crack`**: `~/.config/coderay/` → `~/.config/crack/`, `~/.cache/coderay/` → `~/.cache/crack/`. Confirmed with Mark 2026-08-31 — this is a deliberate exception to "no behavior change," scoped to Task 2 only. Any existing `~/.config/coderay/pricing.json` or `~/.cache/coderay/` on a dev machine is orphaned, not migrated (nothing in either directory is precious: pricing overrides are a cache and the LLM cache is disposable).
- **`default_output_dir` anchors on the current working directory, not `__file__`.** Today it resolves `os.path.dirname(__file__) / ".." / "output"`, which works only because `__main__.py` sits one level below the repo root (`workflow/__main__.py`). After the move, `render.py` sits four levels down (`src/crack/analyses/tour/render.py`), so the same expression would resolve to a directory buried inside the package instead of the repo's `output/` — silently different behavior. This is a deliberate exception to "no behavior change," scoped to Task 5: anchor on `os.getcwd()` instead, matching every documented usage pattern (README/CONTRIBUTING examples all run `crack tour` from the repo root, so `os.getcwd()` reproduces today's `output/` location in normal use) and staying correct for an installed (non-editable) `crack` too, where `__file__` would point into site-packages.
- **`tour.run()` raises `SystemExit` with the same message `ap.error()` used, not the same exit semantics.** Today `ap.error(...)` (argparse) exits with code 2 and prints the parser's usage line first. `run(args)` doesn't have the parser in scope, so it can't reproduce that; it exits with code 1 and no usage line. Confirmed with Mark 2026-08-31 as a sanctioned exception, scoped to Task 5 — not worth threading the parser through the analysis interface for one validation message.
- **`core/runner.py` stays narrow**: `flow.run(shared)`, plus a generic failure-dump hook the caller supplies (spec's Decisions section) — it must not know about tour-specific `PipelineState` keys.
- **`graph/` stays under `analyses/tour/`**, not `core/`, until a second analysis needs import-graph extraction (tracked separately as coderay-wy9; out of scope here).
- **No `crack all`** this iteration (spec Non-goals).
- Run `python -m pytest tests/ -q` after every task; it must report all-green before moving to the next task.

---

## File Structure

```text
pyproject.toml                          # package "crack", src layout, console script "crack"
src/crack/
  __init__.py
  cli.py                                 # argparse subcommand dispatch
  core/
    __init__.py                          # re-exports, same shape as today's coderay_utils/__init__.py
    call_llm.py                          # moved from coderay_utils/call_llm.py, CACHE_DIR -> ~/.cache/crack
    llm.py                               # moved from coderay_utils/llm.py
    crawl.py                             # moved from coderay_utils/crawl.py
    pricing.py                           # moved from coderay_utils/pricing.py, CONFIG_DIR -> ~/.config/crack
    runner.py                            # new: run_flow(flow, shared, out_dir, dump_state)
  analyses/
    __init__.py                          # ANALYSES = {"tour": tour}
    tour/
      __init__.py                        # new: NAME, build_flow, add_arguments, init_shared, run
      nodes.py                           # moved from workflow/nodes.py
      flow.py                            # moved from workflow/flow.py
      render.py                          # new: everything from workflow/__main__.py except arg
                                          # parsing/dispatch (rendering, dry-run estimate, session
                                          # summary, dump_run_state)
      prompts/*.md                       # moved from workflow/prompts/
      instructions/*.md                  # moved from workflow/instructions/
      graph/
        __init__.py                      # moved from workflow/graph/__init__.py
        languages/
          __init__.py                    # moved from workflow/graph/languages/__init__.py
          python.py                      # moved from workflow/graph/languages/python.py
          javascript.py                  # moved from workflow/graph/languages/javascript.py
          typescript.py                  # moved from workflow/graph/languages/typescript.py
tests/                                   # existing tests, import paths updated
```

`coderay_utils/`, `workflow/`, and the top-level `utils/` all go away by the end of Task 6. (`utils/` does not currently exist in this worktree — confirmed empty and already removed — so Task 6 has nothing to delete there; the spec's mention of it is stale.)

---

### Task 1: `pyproject.toml` skeleton and empty `src/crack/` package

**Files:**

- Modify: `pyproject.toml`
- Create: `src/crack/__init__.py`
- Create: `src/crack/core/__init__.py` (empty placeholder, filled in Task 2)
- Create: `src/crack/analyses/__init__.py` (empty placeholder, filled in Task 5)
- Create: `src/crack/analyses/tour/__init__.py` (empty placeholder, filled in Task 5)
- Test: `tests/test_package_skeleton.py`

**Interfaces:**

- Produces: an installed, importable `crack` package with no functional code yet. `workflow`/`coderay_utils` are untouched and still fully functional in this task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_package_skeleton.py
import crack
import crack.core
import crack.analyses
import crack.analyses.tour

def test_crack_package_is_importable():
    assert crack is not None

def test_crack_subpackages_are_importable():
    assert crack.core is not None
    assert crack.analyses is not None
    assert crack.analyses.tour is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_package_skeleton.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crack'`

- [ ] **Step 3: Create the empty package tree**

```bash
mkdir -p src/crack/core src/crack/analyses/tour
touch src/crack/__init__.py src/crack/core/__init__.py \
      src/crack/analyses/__init__.py src/crack/analyses/tour/__init__.py
```

- [ ] **Step 4: Update `pyproject.toml`** — change `name`, switch to `src` layout, add `crack` to the packages list alongside the still-present `workflow`/`coderay_utils` entries (both package trees coexist until Task 6):

```toml
[project]
name = "crack"
version = "0.1.0"
description = "Crawls a repo, picks the files that matter, and writes a multi-chapter tutorial."
requires-python = ">=3.10"
dependencies = [
    "pocketflow>=0.0.3,<0.1",
    "pyyaml>=6.0.3,<7",
    "pathspec>=1.1.1,<2",
    "markdown-it-py>=4.2.0,<5",
    "anthropic>=1.0.0,<2",
]

[project.optional-dependencies]
openai = ["openai>=3.3.1,<4"]
gemini = ["google-genai>=2.19.0,<3"]

[dependency-groups]
dev = ["pytest>=9.1.1,<10"]

[project.scripts]
coderay = "workflow.__main__:main"

[tool.setuptools]
package-dir = {"" = "src", "workflow" = "workflow", "coderay_utils" = "coderay_utils"}
packages = [
    "workflow", "coderay_utils", "workflow.graph", "workflow.graph.languages",
    "crack", "crack.core", "crack.analyses", "crack.analyses.tour",
]

[tool.setuptools.package-data]
workflow = ["prompts/*.md", "instructions/*.md"]
```

Note: `package-dir` maps the bare `""` root to `src/` (where `crack` lives) while pinning `workflow` and `coderay_utils` back to the repo root, since those two packages aren't moving until later tasks. This dual mapping is temporary scaffolding removed in Task 6 once `workflow`/`coderay_utils` are deleted.

- [ ] **Step 5: Regenerate the lockfile and sync**

Run: `uv lock && uv sync`
Expected: resolves cleanly, `crack==0.1.0` (editable) appears in `uv.lock` alongside `coderay`.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_package_skeleton.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Run the full suite to confirm no regression**

Run: `python -m pytest tests/ -q`
Expected: all 139 existing tests still pass, plus the 2 new ones (141 total)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/crack tests/test_package_skeleton.py
git commit -m "Add empty crack package skeleton alongside workflow/coderay_utils"
```

---

### Task 2: Move `coderay_utils/*` → `src/crack/core/*`

**Files:**

- Move: `coderay_utils/call_llm.py` → `src/crack/core/call_llm.py`
- Move: `coderay_utils/llm.py` → `src/crack/core/llm.py`
- Move: `coderay_utils/crawl.py` → `src/crack/core/crawl.py`
- Move: `coderay_utils/pricing.py` → `src/crack/core/pricing.py`
- Modify: `src/crack/core/__init__.py`
- Modify: `workflow/nodes.py` (import line only)
- Modify: `workflow/__main__.py` (import line only)
- Modify: `tests/test_call_llm.py`, `tests/test_crawl.py`, `tests/test_llm.py`, `tests/test_pricing.py`, `tests/test_prompts.py`, `tests/conftest.py` (import paths only)
- Delete: `coderay_utils/` (whole directory, once nothing references it)

**Interfaces:**

- Consumes: the `crack.core` empty package from Task 1.
- Produces: `crack.core.call_llm`, `crack.core.llm`, `crack.core.crawl`, `crack.core.pricing` modules, and `crack.core` re-exporting the same symbol set `coderay_utils/__init__.py` did (`call_llm`, `get_usage`, `max_output_tokens`, `reset_usage`, `resolve_provider_and_model`, `DEFAULT_MAX_OUTPUT_TOKENS`, `read_prompt`, `fill`, `parse_yaml`, `yaml_call`, `list_files`, `safe_read`, `DEFAULT_KEEP_EXT`, `DEFAULT_SKIP_DIR`, `DEFAULT_KEEP_NAMES`, `DEFAULT_MAX_FILE_BYTES`, `cost_for`, `ensure_priced`, `get_price`) — later tasks (and `workflow/nodes.py`/`workflow/__main__.py` in this same task) import from `crack.core`.

- [ ] **Step 1: Move the four files with `git mv` (preserves content and history)**

```bash
git mv coderay_utils/call_llm.py src/crack/core/call_llm.py
git mv coderay_utils/llm.py src/crack/core/llm.py
git mv coderay_utils/crawl.py src/crack/core/crawl.py
git mv coderay_utils/pricing.py src/crack/core/pricing.py
```

- [ ] **Step 2: Rename the on-disk cache/config folder names inside the moved files**

In `src/crack/core/call_llm.py`, update the docstring and `CACHE_DIR`:

```python
# before (lines 12-18, 26, 34):
#   Responses are cached on disk under ~/.cache/coderay/ (or $XDG_CACHE_HOME/coderay
#   ...
#   Clear with: rm -rf ~/.cache/coderay
#   ...
#   python -m coderay_utils.call_llm
# ...
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "coderay")

# after:
#   Responses are cached on disk under ~/.cache/crack/ (or $XDG_CACHE_HOME/crack
#   ...
#   Clear with: rm -rf ~/.cache/crack
#   ...
#   python -m crack.core.call_llm
# ...
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "crack")
```

In `src/crack/core/pricing.py`, update the docstring and `CONFIG_DIR`:

```python
# before (line 1, 36):
"""$/token pricing for the models coderay talks to.
...
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "coderay")

# after:
"""$/token pricing for the models crack talks to.
...
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "crack")
```

- [ ] **Step 3: Update `src/crack/core/__init__.py`** to the same re-export shape as `coderay_utils/__init__.py`:

```python
"""Shared helpers any analysis can use: the LLM wrapper, the crawler, and the
prompt/YAML plumbing in llm.py."""
# Re-exported for `from crack.core import <name>`; not used inside this module.
from .call_llm import (  # noqa: F401
    DEFAULT_MAX_OUTPUT_TOKENS,
    call_llm,
    get_usage,
    max_output_tokens,
    reset_usage,
    resolve_provider_and_model,
)
from .llm import (  # noqa: F401
    read_prompt,
    fill,
    parse_yaml,
    yaml_call,
)
from .crawl import (  # noqa: F401
    list_files,
    safe_read,
    DEFAULT_KEEP_EXT,
    DEFAULT_SKIP_DIR,
    DEFAULT_KEEP_NAMES,
    DEFAULT_MAX_FILE_BYTES,
)
from .pricing import (  # noqa: F401
    cost_for,
    ensure_priced,
    get_price,
)
```

- [ ] **Step 4: Update the two remaining `coderay_utils` importers**

`workflow/nodes.py` line 29:

```python
# before
from coderay_utils import call_llm, fill, list_files, read_prompt, safe_read, yaml_call
# after
from crack.core import call_llm, fill, list_files, read_prompt, safe_read, yaml_call
```

`workflow/__main__.py` lines 25-28:

```python
# before
from coderay_utils import (
    cost_for, ensure_priced, fill, get_usage, list_files, max_output_tokens,
    read_prompt, reset_usage, resolve_provider_and_model, safe_read,
)
# after
from crack.core import (
    cost_for, ensure_priced, fill, get_usage, list_files, max_output_tokens,
    read_prompt, reset_usage, resolve_provider_and_model, safe_read,
)
```

- [ ] **Step 5: Update test imports**

`tests/test_call_llm.py` lines 10-14:

```python
# before
# coderay_utils/__init__.py re-exports call_llm the function under the same name as the
# call_llm module, shadowing `coderay_utils.call_llm` as an attribute -- fetch the
# module directly via importlib instead.
call_llm_module = importlib.import_module("coderay_utils.call_llm")
from coderay_utils.call_llm import _cache_path, _cache_put, call_llm
# after
# crack.core/__init__.py re-exports call_llm the function under the same name as the
# call_llm module, shadowing `crack.core.call_llm` as an attribute -- fetch the
# module directly via importlib instead.
call_llm_module = importlib.import_module("crack.core.call_llm")
from crack.core.call_llm import _cache_path, _cache_put, call_llm
```

`tests/test_call_llm.py` line 392: `from crack.core.call_llm import resolve_provider_and_model`
`tests/test_call_llm.py` lines 511, 539, 564, 611, 668: `from crack.core.call_llm import CACHE_BREAKPOINT`
`tests/test_call_llm.py` line 687: `from crack.core.call_llm import CACHE_BREAKPOINT, _cache_path`

`tests/test_crawl.py` lines 4-5:

```python
# before
import coderay_utils  # noqa: F401  (populates sys.modules["coderay_utils.crawl"])
from coderay_utils.crawl import list_files, safe_read
# after
import crack.core  # noqa: F401  (populates sys.modules["crack.core.crawl"])
from crack.core.crawl import list_files, safe_read
```

`tests/test_llm.py` line 3: `from crack.core.llm import parse_yaml`

`tests/test_pricing.py` — every `from coderay_utils.pricing import ...` and `import coderay_utils.pricing as pricing_module` (lines 1, 34, 46, 58, 67, 75, 84-85, 96-97, 109, 117, 127, 134, 153, 168, 183, 194, 208, 218) becomes `from crack.core.pricing import ...` / `import crack.core.pricing as pricing_module` respectively — mechanical find-replace of `coderay_utils.pricing` → `crack.core.pricing`.

`tests/test_prompts.py` line 4: `from crack.core import fill`
`tests/test_prompts.py` line 23: `from crack.core.call_llm import CACHE_BREAKPOINT`

`tests/conftest.py` line 6: `import crack.core.pricing as pricing_module`

- [ ] **Step 6: Delete the now-empty `coderay_utils/` directory**

```bash
rm -rf coderay_utils/
```

- [ ] **Step 7: Remove `coderay_utils` from `pyproject.toml`**

```toml
[tool.setuptools]
package-dir = {"" = "src", "workflow" = "workflow"}
packages = [
    "workflow", "workflow.graph", "workflow.graph.languages",
    "crack", "crack.core", "crack.analyses", "crack.analyses.tour",
]
```

- [ ] **Step 8: Run the full suite**

Run: `uv lock && uv sync && python -m pytest tests/ -q`
Expected: all 141 tests pass (same count as Task 1 — no new tests added, this task is a pure move)

- [ ] **Step 9: Commit**

```bash
git status --porcelain -uall  # confirm only expected files changed before sweeping them in
git add -A
git commit -m "Move coderay_utils to crack.core; rename config/cache dirs to crack"
```

---

### Task 3: Move `workflow/graph/languages/` → `src/crack/analyses/tour/graph/languages/`

**Files:**

- Move: `workflow/graph/__init__.py` → `src/crack/analyses/tour/graph/__init__.py`
- Move: `workflow/graph/languages/__init__.py` → `src/crack/analyses/tour/graph/languages/__init__.py`
- Move: `workflow/graph/languages/python.py` → `src/crack/analyses/tour/graph/languages/python.py`
- Move: `workflow/graph/languages/javascript.py` → `src/crack/analyses/tour/graph/languages/javascript.py`
- Move: `workflow/graph/languages/typescript.py` → `src/crack/analyses/tour/graph/languages/typescript.py`
- Modify: `workflow/nodes.py` (import line only)
- Modify: `tests/test_graph_python.py`, `tests/test_graph_javascript.py`, `tests/test_graph_typescript.py` (import paths only)

**Interfaces:**

- Consumes: `src/crack/analyses/tour/` package from Task 1.
- Produces: `crack.analyses.tour.graph.languages.REGISTRY` (dict of file extension → extractor module, same shape as today's `workflow.graph.languages.REGISTRY`), consumed by `workflow/nodes.py`'s `ExtractGraph` in this task, and later by the moved `nodes.py` in Task 4.

- [ ] **Step 1: Move the files**

```bash
mkdir -p src/crack/analyses/tour/graph/languages
git mv workflow/graph/__init__.py src/crack/analyses/tour/graph/__init__.py
git mv workflow/graph/languages/__init__.py src/crack/analyses/tour/graph/languages/__init__.py
git mv workflow/graph/languages/python.py src/crack/analyses/tour/graph/languages/python.py
git mv workflow/graph/languages/javascript.py src/crack/analyses/tour/graph/languages/javascript.py
git mv workflow/graph/languages/typescript.py src/crack/analyses/tour/graph/languages/typescript.py
rmdir workflow/graph/languages workflow/graph 2>/dev/null || true
```

The moved files' own content (imports of `tree_sitter`, `tree_sitter_python`, etc.) is unchanged — they're self-contained and never imported anything from `workflow` or `coderay_utils`.

- [ ] **Step 2: Update `workflow/nodes.py`** line 30:

```python
# before
from workflow.graph.languages import REGISTRY
# after
from crack.analyses.tour.graph.languages import REGISTRY
```

- [ ] **Step 3: Update test imports**

`tests/test_graph_python.py` lines 1-2:

```python
# before
import workflow.graph.languages.python as python_module
from workflow.graph.languages.python import imports
# after
import crack.analyses.tour.graph.languages.python as python_module
from crack.analyses.tour.graph.languages.python import imports
```

`tests/test_graph_javascript.py` lines 1-2: same pattern with `javascript_module` / `.javascript`.
`tests/test_graph_typescript.py` lines 1-2: same pattern with `typescript_module` / `.typescript`.

- [ ] **Step 4: Update `pyproject.toml` packages list**

```toml
packages = [
    "workflow",
    "crack", "crack.core", "crack.analyses", "crack.analyses.tour",
    "crack.analyses.tour.graph", "crack.analyses.tour.graph.languages",
]
```

(`workflow.graph`/`workflow.graph.languages` are dropped — that code no longer lives under `workflow/`.)

- [ ] **Step 5: Run the full suite**

Run: `uv sync && python -m pytest tests/ -q`
Expected: all 141 tests pass

- [ ] **Step 6: Commit**

```bash
git status --porcelain -uall  # confirm only expected files changed before sweeping them in
git add -A
git commit -m "Move import-graph extractors to crack.analyses.tour.graph"
```

---

### Task 4: Move `workflow/nodes.py`, `flow.py`, `prompts/`, `instructions/` → `src/crack/analyses/tour/`

**Files:**

- Move: `workflow/nodes.py` → `src/crack/analyses/tour/nodes.py`
- Move: `workflow/flow.py` → `src/crack/analyses/tour/flow.py`
- Move: `workflow/prompts/*.md` (4 files) → `src/crack/analyses/tour/prompts/*.md`
- Move: `workflow/instructions/*.md` (4 files) → `src/crack/analyses/tour/instructions/*.md`
- Modify: `src/crack/analyses/tour/nodes.py` (docstring path references, `resources.files()` call, import lines)
- Modify: `src/crack/analyses/tour/flow.py` (import line only)
- Modify: `workflow/__main__.py` (import lines only)
- Modify: `tests/test_nodes.py`, `tests/test_flow.py` (import paths only)

**Interfaces:**

- Consumes: `crack.analyses.tour.graph.languages.REGISTRY` (Task 3), `crack.core` (Task 2).
- Produces: `crack.analyses.tour.nodes.{PipelineState, SmartCrawl, ExtractGraph, Analyze, Relate, WriteChapters, CODEBASE_BUDGET, PROMPTS_DIR, INSTRUCTIONS_DIR, load_instructions, slug}` and `crack.analyses.tour.flow.create_tour_flow()` — consumed by `workflow/__main__.py` in this task, and by `analyses/tour/__init__.py` and `render.py` in Task 5.

- [ ] **Step 1: Move the files**

```bash
git mv workflow/nodes.py src/crack/analyses/tour/nodes.py
git mv workflow/flow.py src/crack/analyses/tour/flow.py
mkdir -p src/crack/analyses/tour/prompts src/crack/analyses/tour/instructions
git mv workflow/prompts/analyze-relationships.md src/crack/analyses/tour/prompts/analyze-relationships.md
git mv workflow/prompts/identify-abstractions.md src/crack/analyses/tour/prompts/identify-abstractions.md
git mv workflow/prompts/select-files.md src/crack/analyses/tour/prompts/select-files.md
git mv workflow/prompts/write-chapter.md src/crack/analyses/tour/prompts/write-chapter.md
git mv workflow/instructions/architecture-review.md src/crack/analyses/tour/instructions/architecture-review.md
git mv workflow/instructions/beginner-tutorial.md src/crack/analyses/tour/instructions/beginner-tutorial.md
git mv workflow/instructions/onboarding-guide.md src/crack/analyses/tour/instructions/onboarding-guide.md
git mv workflow/instructions/security-audit.md src/crack/analyses/tour/instructions/security-audit.md
rmdir workflow/prompts workflow/instructions 2>/dev/null || true
```

- [ ] **Step 2: Update `src/crack/analyses/tour/nodes.py`**

Lines 1-9 (module docstring — update the file path references):

```python
"""Codebase Knowledge Builder nodes.

Five steps from the book chapter (plus a deterministic graph-extraction step):
  1. SmartCrawl    walk repo, then ask the LLM which files matter
  1.5 ExtractGraph parse selected files for a deterministic import graph
  2. Analyze       extract 5-10 core abstractions as YAML
  3. Relate        map abstractions to each other as YAML edges
  4. WriteChapters one chapter per abstraction, with SEQUENTIAL CONTEXT
  5. (rendering happens in crack/analyses/tour/render.py)
```

Line 12 (`coderay_utils.yaml_call` reference — already just prose, but keep it accurate):

````python
  - SmartCrawl, Analyze, and Relate parse a ```yaml reply through crack.core.yaml_call,
````

Lines 18-20 (same prose fix):

```python
  - File reads in the main path raise. The only swallowed errors are per file decode
    errors inside crack.core.safe_read(), which is correct: we don't want one binary blob
    to kill a walk over 10,000 files.
```

Line 29:

```python
# before
from coderay_utils import call_llm, fill, list_files, read_prompt, safe_read, yaml_call
# after
from crack.core import call_llm, fill, list_files, read_prompt, safe_read, yaml_call
```

Line 30 (already updated to `crack.analyses.tour.graph.languages` in Task 3 — no change here).

Lines 32-33:

```python
# before
PROMPTS_DIR = resources.files("workflow") / "prompts"
INSTRUCTIONS_DIR = resources.files("workflow") / "instructions"
# after
PROMPTS_DIR = resources.files("crack.analyses.tour") / "prompts"
INSTRUCTIONS_DIR = resources.files("crack.analyses.tour") / "instructions"
```

Line 177 (`ExtractGraph` docstring path reference):

```python
# before
    """Parses each selected file with a per-extension tree-sitter extractor
    (workflow/graph/languages/) and records import edges that land inside
# after
    """Parses each selected file with a per-extension tree-sitter extractor
    (crack/analyses/tour/graph/languages/) and records import edges that land inside
```

- [ ] **Step 3: Update `src/crack/analyses/tour/flow.py`** line 3:

```python
# before
from workflow.nodes import Analyze, ExtractGraph, Relate, SmartCrawl, WriteChapters
# after
from crack.analyses.tour.nodes import Analyze, ExtractGraph, Relate, SmartCrawl, WriteChapters
```

- [ ] **Step 4: Update `workflow/__main__.py`** lines 29-37:

```python
# before
from workflow.flow import create_tour_flow
from workflow.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    SmartCrawl,
    load_instructions,
)
# after
from crack.analyses.tour.flow import create_tour_flow
from crack.analyses.tour.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    SmartCrawl,
    load_instructions,
)
```

- [ ] **Step 5: Update test imports**

`tests/test_nodes.py` lines 3-5:

```python
# before
import coderay_utils.llm as llm_module
import workflow.nodes as nodes_module
from workflow.nodes import Analyze, ExtractGraph, PipelineState, Relate, SmartCrawl
# after
import crack.core.llm as llm_module
import crack.analyses.tour.nodes as nodes_module
from crack.analyses.tour.nodes import Analyze, ExtractGraph, PipelineState, Relate, SmartCrawl
```

`tests/test_flow.py` lines 1-3:

```python
# before
import coderay_utils.llm as llm_module
import workflow.nodes as nodes_module
from workflow.flow import create_tour_flow
# after
import crack.core.llm as llm_module
import crack.analyses.tour.nodes as nodes_module
from crack.analyses.tour.flow import create_tour_flow
```

- [ ] **Step 6: Update `pyproject.toml` package-data and packages**

```toml
[tool.setuptools]
package-dir = {"" = "src", "workflow" = "workflow"}
packages = [
    "workflow",
    "crack", "crack.core", "crack.analyses", "crack.analyses.tour",
    "crack.analyses.tour.graph", "crack.analyses.tour.graph.languages",
]

[tool.setuptools.package-data]
"crack.analyses.tour" = ["prompts/*.md", "instructions/*.md"]
```

(The old `workflow = ["prompts/*.md", "instructions/*.md"]` package-data entry is removed — those globs no longer exist under `workflow/`.)

- [ ] **Step 7: Run the full suite**

Run: `uv lock && uv sync && python -m pytest tests/ -q`
Expected: all 141 tests pass

- [ ] **Step 8: Commit**

```bash
git status --porcelain -uall  # confirm only expected files changed before sweeping them in
git add -A
git commit -m "Move pipeline nodes, flow, prompts, and instructions to crack.analyses.tour"
```

---

### Task 5: Add `core/runner.py`, split `workflow/__main__.py` into `cli.py` + `analyses/tour/render.py` + `analyses/tour/__init__.py`

**Files:**

- Create: `src/crack/core/runner.py`
- Create: `src/crack/cli.py`
- Create: `src/crack/analyses/tour/render.py`
- Modify: `src/crack/analyses/tour/__init__.py` (was an empty placeholder from Task 1)
- Modify: `src/crack/analyses/__init__.py` (was an empty placeholder from Task 1)
- Modify: `tests/test_main.py` (imports + the `--version` subprocess test)
- Delete: `workflow/__main__.py`

**Interfaces:**

- Consumes: `crack.analyses.tour.nodes` and `crack.analyses.tour.flow` (Task 4), `crack.core` (Task 2).
- Produces:
  - `crack.core.runner.run_flow(flow, shared, out_dir, dump_state) -> None` — runs `flow.run(shared)`; on any exception, calls `dump_state(shared, out_dir)`, prints `f"\nPipeline failed. Wrote partial run state to {state_path}"`, and re-raises. Generic across any future analysis: it takes the dump callback as a parameter instead of knowing `PipelineState`'s shape.
  - `crack.analyses.tour.render` module exposing every function `workflow/__main__.py` had except `main()`: `md_to_html`, `mermaid_label`, `build_mermaid`, `staleness_disclaimer`, `chapter_html_name`, `available_lenses`, `write_text`, `build_related_links`, `write_chapter_files`, `write_index_md`, `write_index_html`, `format_session_summary`, `estimate_dry_run_cost`, `format_dry_run_summary`, `dump_run_state`, `default_output_dir`, plus the module-level constants `MERMAID_LEGEND`, `SHARED_STYLE`, `MERMAID_SCRIPT`, `INDEX_HTML_TEMPLATE`, `CHAPTER_HTML_TEMPLATE`, `DRY_RUN_CHAPTER_GUESS`.
  - `crack.analyses.tour`: `NAME = "tour"`, `build_flow() -> Flow`, `add_arguments(parser) -> None`, `init_shared(args) -> dict`, `run(args) -> None` — consumed by `cli.py` and by `crack.analyses.ANALYSES`. (The spec's sketch showed `init_shared(args, out_dir)`; tour's own pipeline never reads `out_dir` from `shared` — every render function that needs it takes `out` as an explicit argument — so the unused parameter is dropped here rather than carried as speculative scaffolding. Add it back if a future analysis genuinely needs `out_dir` inside `shared`.)
  - `crack.analyses.ANALYSES = {"tour": crack.analyses.tour}` — consumed by `cli.py`.
  - `crack.cli.main() -> None` — the new console-script entry point.

- [ ] **Step 1: Create `src/crack/core/runner.py`**

```python
"""Runs a pipeline flow against a shared state dict, common to any analysis."""

def run_flow(flow, shared, out_dir, dump_state):
    """Run `flow` against `shared`. On an unhandled exception, call
    `dump_state(shared, out_dir)` to write whatever partial progress exists,
    print where it landed, and re-raise."""
    try:
        flow.run(shared)
    except Exception:
        state_path = dump_state(shared, out_dir)
        print(f"\nPipeline failed. Wrote partial run state to {state_path}")
        raise
```

- [ ] **Step 2: Create `src/crack/analyses/tour/render.py`**

Move every function and constant from `workflow/__main__.py` _except_ `main()` verbatim, updating only the import block at the top:

```python
"""Rendering, cost estimation, and session-summary formatting for the tour analysis."""
import html
import json
import os
import re
from datetime import date

from markdown_it import MarkdownIt

from crack.core import (
    cost_for, fill, list_files, max_output_tokens,
    read_prompt, safe_read,
)
from crack.analyses.tour.nodes import (
    CODEBASE_BUDGET,
    INSTRUCTIONS_DIR,
    PROMPTS_DIR,
    PipelineState,
    SmartCrawl,
    load_instructions,
)

# CommonMark parser. Unlike python-markdown's fenced_code extension, this
# correctly handles fenced code blocks indented inside list items.
_MD = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False}).enable(["table", "strikethrough"])
```

`get_usage` is not imported here: no function in `render.py` calls it. It's called by `tour/__init__.py`'s `run()` (Step 4 below), which imports it directly from `crack.core`. `read_prompt` stays because `estimate_dry_run_cost` uses it.

Then append, verbatim (only the docstring path comment inside `build_related_links` needs a path update):

```python
def mermaid_label(s):
    """Mermaid labels have no escape syntax; restrict to characters that can't break out."""
    return re.sub(r'[^\w .,:/()\[\]-]', '', s)[:60]

MERMAID_LEGEND = (
    "Solid arrows are backed by a real import between the files each abstraction claims; "
    "dashed arrows are the model's judgment."
)

def build_mermaid(abstractions, relationships):
    ids = {a["name"]: f"A{i}" for i, a in enumerate(abstractions)}
    lines = ["flowchart TD"]
    for i, a in enumerate(abstractions):
        lines.append(f'    A{i}["{mermaid_label(a["name"])}"]')
    for r in relationships:
        if r["from"] in ids and r["to"] in ids:
            label = mermaid_label(r["label"][:30])
            arrow = "--" if r.get("source") == "EXTRACTED" else "-."
            head = "-->" if r.get("source") == "EXTRACTED" else ".->"
            lines.append(f'    {ids[r["from"]]} {arrow} "{label}" {head} {ids[r["to"]]}')
    return "\n".join(lines)
```

(`SHARED_STYLE`, `MERMAID_SCRIPT`, `INDEX_HTML_TEMPLATE`, `CHAPTER_HTML_TEMPLATE`, `staleness_disclaimer`, `chapter_html_name`, `available_lenses`, `write_text`, `build_related_links`, `write_chapter_files`, `write_index_md`, `write_index_html`, `format_session_summary`, `DRY_RUN_CHAPTER_GUESS`, `_codebase_preview_text`, `estimate_dry_run_cost`, `format_dry_run_summary` all move unchanged — same bodies as `workflow/__main__.py` lines 82-402, just relocated into this file. `md_to_html` moves unchanged too, lines 44-54.)

`build_related_links`'s docstring (originally lines 197-204) gets one path update:

```python
def build_related_links(chapter_name, relationships, filenames):
    """Related-chapter links for one chapter, both directions of the Relationship graph.

    Relate validates every edge has a from/to/label string before it reaches shared
    state (crack/analyses/tour/nodes.py), but an edge naming an abstraction dropped from
    `filenames` by a codebase-budget cut is still possible, so that case is skipped
    rather than raised.
    """
```

`dump_run_state` (originally lines 405-418) moves unchanged — its curated-fields behavior (only `selected_files`, abstraction/chapter _names_, `order`, `relationships`) is exactly what `tests/test_main.py::test_dump_run_state_captures_partial_progress` and `::test_dump_run_state_handles_empty_shared` assert, and must not change:

```python
def dump_run_state(shared: PipelineState, out):
    """Write whatever progress the pipeline made to a JSON file, for post-mortem
    on an unhandled failure deep into a run (e.g. the 3rd LLM retry still failing
    on chapter 7 of 10)."""
    state = {
        "selected_files": shared.get("selected_files"),
        "abstractions": [a["name"] for a in shared["abstractions"]] if shared.get("abstractions") else None,
        "order": shared.get("order"),
        "relationships": shared.get("relationships"),
        "chapters_completed": [c["name"] for c in shared["chapters"]] if shared.get("chapters") else None,
    }
    path = os.path.join(out, "run_state.json")
    write_text(path, json.dumps(state, indent=2))
    return path
```

`default_output_dir` (originally lines 421-426) changes its anchor — see the Global Constraints note on why `__file__` can't be reused after the move:

```python
def default_output_dir(repo_path, instructions):
    """Keyed on both repo name and lens, so re-running with a different
    --instructions writes to a separate directory instead of colliding with
    (and leaving orphaned chapter files from) a prior run's output. Anchored
    on the current working directory, not this file's location, so it lands
    in the same place whether crack is run from an editable checkout or
    installed as a tool."""
    name = os.path.basename(os.path.abspath(repo_path))
    return os.path.join(os.getcwd(), "output", f"{name}-{instructions}-tour")
```

- [ ] **Step 3: Run this task's first checkpoint test**

Run: `python -c "from crack.analyses.tour import render; print(render.MERMAID_LEGEND)"`
Expected: prints the legend string with no import errors

- [ ] **Step 4: Create `src/crack/analyses/tour/__init__.py`**

```python
"""tour: the default analysis. Crawls a repo, extracts a deterministic import
graph, identifies abstractions, relates them, and writes a multi-chapter tour."""
import os
import time
from datetime import date

from crack.core import ensure_priced, get_usage, reset_usage, resolve_provider_and_model
from crack.core.runner import run_flow
from crack.analyses.tour.flow import create_tour_flow
from crack.analyses.tour.render import (
    available_lenses,
    build_mermaid,
    default_output_dir,
    dump_run_state,
    estimate_dry_run_cost,
    format_dry_run_summary,
    format_session_summary,
    write_chapter_files,
    write_index_html,
    write_index_md,
)

NAME = "tour"

def build_flow():
    return create_tour_flow()

def add_arguments(parser) -> None:
    parser.add_argument("--instructions", default="beginner-tutorial", choices=available_lenses())
    parser.add_argument("--dry-run", action="store_true")

def init_shared(args) -> dict:
    return {"repo_path": args.repo_path, "instructions": args.instructions}

def run(args) -> None:
    # Exit code 1, no usage line -- not the same as argparse's ap.error() (code 2,
    # usage printed), a sanctioned exception (see Global Constraints): run(args)
    # has no parser in scope, and threading one through isn't worth it for one check.
    if not os.path.isdir(args.repo_path):
        raise SystemExit(f"{args.repo_path} is not a directory")

    if args.dry_run:
        try:
            provider, model = resolve_provider_and_model()
        except RuntimeError:
            provider, model = "anthropic", "claude-sonnet-5"
        print(format_dry_run_summary(estimate_dry_run_cost(args.repo_path, args.instructions, provider, model)))
        return

    provider, model = resolve_provider_and_model()
    ensure_priced(provider, model)

    name = os.path.basename(os.path.abspath(args.repo_path))
    out = args.out or default_output_dir(args.repo_path, args.instructions)
    os.makedirs(out, exist_ok=True)

    reset_usage()
    wall_start = time.perf_counter()

    shared = init_shared(args)
    run_flow(build_flow(), shared, out, dump_run_state)

    wall_seconds = time.perf_counter() - wall_start

    chapters = shared["chapters"]
    mermaid = build_mermaid(shared["abstractions"], shared["relationships"])

    generated_at = date.today().isoformat()
    write_chapter_files(chapters, name, out, shared["relationships"], generated_at)
    write_index_md(chapters, name, args.instructions, shared["summary"], mermaid, out, generated_at)
    write_index_html(
        chapters, name, args.instructions, shared["summary"], mermaid,
        shared["selected_files"], shared["selection_reasoning"], out, generated_at,
    )

    print(f"\nWrote tour to {out}/")
    print(f"  Open {out}/index.html in a browser")
    print()
    print(format_session_summary(get_usage(), wall_seconds))
```

Note: `args.out` and `--out` are added by `cli.py` (Step 6 below), not by `add_arguments` — matching the spec's dispatch pseudocode where `repo_path` and `--out` are added once by the shared subparser loop, and each analysis's `add_arguments` only adds its own flags (`--instructions`, `--dry-run`).

- [ ] **Step 5: Create `src/crack/analyses/__init__.py`**

```python
"""Registry of available analyses: name -> module implementing the analysis
interface (NAME, build_flow, add_arguments, init_shared, run)."""
from crack.analyses import tour

ANALYSES = {tour.NAME: tour}
```

- [ ] **Step 6: Create `src/crack/cli.py`**

```python
"""crack: dispatches to a named analysis subcommand."""
import argparse
from importlib.metadata import version

from crack.analyses import ANALYSES

def main():
    parser = argparse.ArgumentParser(prog="crack")
    parser.add_argument("--version", action="version", version=f"crack {version('crack')}")
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    for name, analysis in ANALYSES.items():
        sub = subparsers.add_parser(name)
        sub.add_argument("repo_path")
        sub.add_argument("--out", default=None)
        analysis.add_arguments(sub)
    args = parser.parse_args()
    ANALYSES[args.analysis].run(args)

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Delete `workflow/__main__.py`**

```bash
rm workflow/__main__.py
rmdir workflow 2>/dev/null || true
```

(`workflow/` now has nothing left in it — `workflow/__init__.py` was the only remaining file, and it was empty. If `rmdir` reports the directory not empty, list its contents before forcing anything — that would mean an earlier task missed a file.)

- [ ] **Step 8: Update `tests/test_main.py`**

```python
# before (lines 1-23)
import json
import os
import subprocess
import sys
from importlib.metadata import version

from workflow.__main__ import (
    MERMAID_SCRIPT,
    available_lenses,
    build_mermaid,
    build_related_links,
    default_output_dir,
    dump_run_state,
    estimate_dry_run_cost,
    format_dry_run_summary,
    format_session_summary,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)
from workflow.nodes import slug

def test_version_flag_prints_installed_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "workflow", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"coderay {version('coderay')}"

# after
import json
import os
import subprocess
import sys
from importlib.metadata import version

from crack.analyses.tour.render import (
    MERMAID_SCRIPT,
    available_lenses,
    build_mermaid,
    build_related_links,
    default_output_dir,
    dump_run_state,
    estimate_dry_run_cost,
    format_dry_run_summary,
    format_session_summary,
    md_to_html,
    mermaid_label,
    write_chapter_files,
    write_index_html,
    write_index_md,
)
from crack.analyses.tour.nodes import slug

def test_version_flag_prints_installed_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == f"crack {version('crack')}"
```

Every other test in `tests/test_main.py` (the `build_mermaid`, `write_index_html`, `dump_run_state`, `format_session_summary`, etc. tests) calls the imported names directly and needs no further change — only the import block and the version test's literal strings move.

- [ ] **Step 9: Update `pyproject.toml`**

```toml
[project.scripts]
crack = "crack.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}
packages = [
    "crack", "crack.core", "crack.analyses", "crack.analyses.tour",
    "crack.analyses.tour.graph", "crack.analyses.tour.graph.languages",
]

[tool.setuptools.package-data]
"crack.analyses.tour" = ["prompts/*.md", "instructions/*.md"]
```

**Keep `package-dir = {"" = "src"}`.** setuptools' src-layout auto-discovery only activates when `packages` is _not_ set explicitly. This plan lists `packages` explicitly (so `pyproject.toml` stays an accurate map of what actually ships, matching the file's style since Task 1), which means the `"" = "src"` root mapping must stay too — drop it and setuptools looks for `crack/` at the repo root and the build fails. What actually goes away here is the _dual_ mapping from Task 1-4 (`"workflow" = "workflow"`, `"coderay_utils" = "coderay_utils"`), since those packages no longer exist.

- [ ] **Step 10: Run the full suite**

Run: `uv lock && uv sync && python -m pytest tests/ -q`
Expected: all 141 tests pass. The old `coderay` console script is gone; only `crack` exists now.

- [ ] **Step 11: Manual smoke check of the CLI wiring** (no API key needed — `--version` doesn't touch the pipeline)

Run: `python -m crack.cli --version`
Expected: prints `crack 0.1.0`

Run: `python -m crack.cli --help`
Expected: shows `tour` as the only subcommand

- [ ] **Step 12: Commit**

```bash
git status --porcelain -uall  # confirm only expected files changed before sweeping them in
git add -A
git commit -m "Split workflow/__main__.py into cli.py, core/runner.py, and analyses/tour/render.py"
```

---

### Task 6: Clean up leftover `workflow` references and finalize `pyproject.toml`

**Files:**

- Modify: `pyproject.toml` (final sanity pass)
- Verify: no remaining `workflow`/`coderay_utils` references anywhere in `src/`, `tests/`, or `pyproject.toml`

**Interfaces:**

- Consumes: nothing new — this task is verification and cleanup, not new functionality.
- Produces: nothing new — confirms Tasks 1-5 left no stragglers.

- [ ] **Step 1: Grep for any remaining old-package references**

Run: `grep -rn "workflow\." src/ tests/ pyproject.toml; grep -rn "coderay_utils" src/ tests/ pyproject.toml; grep -rn "import workflow\|from workflow" src/ tests/`

Expected: no output (empty). If anything shows up, it's a straggler import missed in an earlier task — fix it now before continuing (don't add a compatibility shim).

- [ ] **Step 2: Confirm `workflow/` and `coderay_utils/` no longer exist on disk**

Run: `ls workflow coderay_utils 2>&1`
Expected: `ls: workflow: No such file or directory` and same for `coderay_utils`

- [ ] **Step 3: Confirm the dead top-level `utils/` still doesn't exist** (spec flagged it as dead weight; already absent in this worktree)

Run: `ls utils 2>&1`
Expected: `ls: utils: No such file or directory`

- [ ] **Step 4: Run the full suite one more time**

Run: `python -m pytest tests/ -q`
Expected: all 141 tests pass

- [ ] **Step 5: Commit** (only if Step 1 found and fixed something; otherwise skip — nothing to commit)

```bash
git status --porcelain -uall  # confirm only expected files changed before sweeping them in
git add -A
git commit -m "Remove stray workflow/coderay_utils references"
```

---

### Task 7: Update docs for the new command and layout

**Files:**

- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `Makefile`

**Interfaces:** none — documentation only, no code interfaces.

- [ ] **Step 1: Update `README.md`**

Line 9-11 (package layout description):

```markdown
# before

- [`workflow/`](workflow/) — the four pipeline stages: SmartCrawl, Analyze, Relate, WriteChapters. SmartCrawl, Analyze, and Relate parse structured YAML output and retry on a bad response (`coderay_utils.yaml_call`); WriteChapters calls the LLM directly and retries via PocketFlow's own `Node(max_retries=3)`.
- [`workflow/prompts/`](workflow/prompts/) — the prompt template each stage sends to the LLM, one file per stage.
- [`workflow/instructions/`](workflow/instructions/) — four swappable output styles (see "Swap the output style" below). Same pipeline, different framing for the same chapters.
- [`skill/CODEBASE-TOUR.md`](skill/CODEBASE-TOUR.md) — the same workflow packaged as an agent skill.

# after

- [`src/crack/analyses/tour/`](src/crack/analyses/tour/) — the `tour` analysis: SmartCrawl, ExtractGraph, Analyze, Relate, WriteChapters. SmartCrawl, Analyze, and Relate parse structured YAML output and retry on a bad response (`crack.core.yaml_call`); WriteChapters calls the LLM directly and retries via PocketFlow's own `Node(max_retries=3)`.
- [`src/crack/analyses/tour/prompts/`](src/crack/analyses/tour/prompts/) — the prompt template each stage sends to the LLM, one file per stage.
- [`src/crack/analyses/tour/instructions/`](src/crack/analyses/tour/instructions/) — four swappable output styles (see "Swap the output style" below). Same pipeline, different framing for the same chapters.
- [`skill/CODEBASE-TOUR.md`](skill/CODEBASE-TOUR.md) — the same analysis packaged as an agent skill.
```

Line 21: `python -m workflow path/to/repo   # or just: coderay path/to/repo` → `crack tour path/to/repo`

Lines 58-60, 73 (example invocations): `python -m workflow path/to/repo --instructions X` → `crack tour path/to/repo --instructions X`; `python -m workflow path/to/repo --dry-run` → `crack tour path/to/repo --dry-run`

Line 55: `Same pipeline and code, driven by a different file under \`workflow/instructions/\``→ `` driven by a different file under`src/crack/analyses/tour/instructions/` ``

Line 96: `Built-in pricing covers the default model for each provider. For any other model, coderay prompts you once, interactively, for $/1M token pricing, and saves it to \`~~/.config/coderay/pricing.json\`.`→ `` ...crack prompts you once... saves it to`~~/.config/crack/pricing.json`. ``

Line 118: ``the selection rules in [`workflow/prompts/select-files.md`](workflow/prompts/select-files.md)`` → ``the selection rules in [`src/crack/analyses/tour/prompts/select-files.md`](src/crack/analyses/tour/prompts/select-files.md)``

- [ ] **Step 2: Update `CONTRIBUTING.md`**

Line 10: ``a key only to run the pipeline against a real repo (`python -m workflow path/to/repo`)`` → ``(`crack tour path/to/repo`)``

Line 24: ``Parse LLM YAML output through `coderay_utils.yaml_call`... Do not add a new parse-and-retry loop in `workflow/nodes.py`.`` → ``through `crack.core.yaml_call`... in `src/crack/analyses/tour/nodes.py`.``

Line 25: `` `workflow/__main__.py` once had a confirmed stored-XSS ... before you change that file's rendering code. `` → `` `src/crack/analyses/tour/render.py` once had a confirmed stored-XSS (cross-site scripting) bug here. Read `.full-review/02a-security.md` before you change that file's rendering code. ``

Line 27: ``Add a new output lens by adding one file to `workflow/instructions/`.`` → ``to `src/crack/analyses/tour/instructions/`.``

- [ ] **Step 3: Update `CLAUDE.md`**

Line 68: `pip install -e .              # install this package (workflow/ + coderay_utils/) in editable mode` → `# install this package (src/crack/) in editable mode`

Line 72: `python -m workflow path/to/repo   # run the pipeline end to end (needs an API key, see .env.example)` → `crack tour path/to/repo   # run the tour analysis end to end (needs an API key, see .env.example)`

Line 79: ``A PocketFlow pipeline with four sequential nodes (`workflow/nodes.py`, wired in `workflow/flow.py`):`` → ``(`src/crack/analyses/tour/nodes.py`, wired in `src/crack/analyses/tour/flow.py`):``

Line 85: ``**SmartCrawl** walks the target repo (`coderay_utils/crawl.py`)...`` → ``(`src/crack/core/crawl.py`)...``

Line 86: ``call the LLM via `coderay_utils.call_llm` and parse its YAML output via `coderay_utils.yaml_call`...`` → ``via `crack.core.call_llm`... via `crack.core.yaml_call`...``

Line 87: `` `workflow/__main__.py` renders the pipeline's output (`shared` dict, typed as `PipelineState` in `workflow/nodes.py`) to markdown + HTML. `` → `` `src/crack/analyses/tour/render.py` renders the analysis's output (`shared` dict, typed as `PipelineState` in `src/crack/analyses/tour/nodes.py`) to markdown + HTML. ``

Line 88: `` `workflow/prompts/*.md` are the four LLM prompt templates; `workflow/instructions/*.md` are swappable output lenses... `` → `` `src/crack/analyses/tour/prompts/*.md`... `src/crack/analyses/tour/instructions/*.md`... ``

Line 94: ``see `.full-review/02a-security.md` before touching `workflow/__main__.py`'s rendering code.`` → ``before touching `src/crack/analyses/tour/render.py`'s rendering code.``

Line 95: ``a bespoke `parse_yaml`/`.format()` combo in `workflow/nodes.py`... Reuse `coderay_utils.yaml_call` and `coderay_utils.fill()`...`` → ``in `src/crack/analyses/tour/nodes.py`... Reuse `crack.core.yaml_call` and `crack.core.fill()`...``

- [ ] **Step 4: Update `AGENTS.md`** — mirror any of the same coderay/workflow path references found in `CLAUDE.md` Step 3 that also appear in `AGENTS.md` (both files are kept in sync per the project's own convention noted at the bottom of `CLAUDE.md`). Re-run the grep from Task 6 Step 1 scoped to `AGENTS.md` to confirm parity after editing.

- [ ] **Step 5: Update `Makefile`**

```makefile
# before
install-global: ## Install the coderay CLI onto your PATH via uv tool
	uv tool install --editable .

uninstall: ## Uninstall the coderay CLI
	uv tool uninstall coderay
# after
install-global: ## Install the crack CLI onto your PATH via uv tool
	uv tool install --editable .

uninstall: ## Uninstall the crack CLI
	uv tool uninstall crack
```

- [ ] **Step 6: Grep the whole repo (excluding `.git`, `.beads`, `docs/superpowers`, and this plan itself) for stray `coderay`/`workflow` mentions that should have been caught above**

Run: `grep -rln "python -m workflow\|coderay_utils\|workflow/nodes\|workflow/__main__\|workflow/prompts\|workflow/instructions" --include="*.md" --include="Makefile" . | grep -v '.git/\|.beads/\|docs/superpowers/'`

Expected: empty, or only files intentionally out of scope (e.g. `.full-review/*.md`, which documents a past review and is a historical record, not live documentation — leave it untouched).

Already verified during planning: `.github/workflows/tests.yml` and `release.yml` are name-agnostic (`uv sync --locked`, `pytest tests/ -q`, `uv build` — no hardcoded `coderay`/`workflow` string anywhere), so neither needs an edit.

- [ ] **Step 7: Commit**

```bash
git add README.md CONTRIBUTING.md CLAUDE.md AGENTS.md Makefile
git commit -m "Update docs and Makefile for the crack CLI and src/crack/ layout"
```

---

### Task 8: End-to-end smoke test

**Files:**

- Create: `tests/test_smoke.py`

**Interfaces:**

- Consumes: `crack.cli.main` (Task 5), a fixture repo under `tests/fixtures/` (created in this task if one doesn't already exist).

- [ ] **Step 1: Check whether a fixture repo already exists for other tests**

Run: `find tests -iname "*fixture*" -o -iname "*sample*repo*"`

If one exists, reuse it. If not, create a minimal one in this step (a two-or-three-file toy Python package is enough — the smoke test only needs the CLI to run end-to-end, not to produce meaningful chapters).

```bash
mkdir -p tests/fixtures/toy_repo
cat > tests/fixtures/toy_repo/main.py <<'EOF'
"""Entry point for the toy app."""
from greeter import greet

def main():
    print(greet("world"))

if __name__ == "__main__":
    main()
EOF
cat > tests/fixtures/toy_repo/greeter.py <<'EOF'
"""Greeting helper used by main.py."""

def greet(name):
    return f"Hello, {name}!"
EOF
```

- [ ] **Step 2: Write the smoke test, skipped without an API key** (matching the sibling project's own `test_smoke.py` pattern per the spec's Testing section)

```python
# tests/test_smoke.py
import os
import subprocess
import sys

import pytest

FIXTURE_REPO = os.path.join(os.path.dirname(__file__), "fixtures", "toy_repo")

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")),
    reason="no API key set; smoke test needs a real LLM call",
)

def test_crack_tour_runs_end_to_end(tmp_path):
    out_dir = str(tmp_path / "tour-output")
    result = subprocess.run(
        [sys.executable, "-m", "crack.cli", "tour", FIXTURE_REPO, "--out", out_dir],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert os.path.isfile(os.path.join(out_dir, "index.md"))
    assert os.path.isfile(os.path.join(out_dir, "index.html"))
```

- [ ] **Step 3: Run it without an API key set to confirm the skip path works**

Run: `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY python -m pytest tests/test_smoke.py -v`
Expected: `SKIPPED (no API key set; smoke test needs a real LLM call)`

- [ ] **Step 4: If an API key is available, run it for real** (optional — do this only if `.env` has a usable key; otherwise leave it to CI/a future run)

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS, with `index.md`/`index.html` written to the temp output dir

- [ ] **Step 5: Run the full suite one final time**

Run: `python -m pytest tests/ -q`
Expected: all 142 tests pass (141 + this one, real-run-or-skip either way)

- [ ] **Step 6: Commit**

```bash
git add tests/test_smoke.py tests/fixtures/toy_repo
git commit -m "Add end-to-end smoke test for crack tour, skipped without an API key"
```

---

## After Task 8

This plan covers spec steps 2-8 of the migration order. Step 1 (GitHub repo rename) is deliberately excluded — confirm with Mark before doing it separately. Once all 8 tasks are green and committed:

1. Open a PR from `worktree-coderay-crack-restructure` against `main`.
2. Trigger the same Copilot review loop PR #23 got (`request_copilot_review`), and work through findings the same way — confirm any claim about a library/API against source before agreeing or disagreeing, per the gotcha from PR #23.
3. Merge once green and approved.
