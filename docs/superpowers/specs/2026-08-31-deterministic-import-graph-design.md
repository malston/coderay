# Deterministic call/import graph for Relate (coderay-bum)

## Problem

Relate (`workflow/nodes.py:195-221`) invents every relationship between abstractions purely
from LLM judgment (`workflow/prompts/analyze-relationships.md`). There's no structural ground
truth behind any edge -- the LLM can assert "A uses B" with no way for a reader to tell that
from a guess. This is the same failure mode the Evidence discipline block
(`workflow/prompts/write-chapter.md`, from coderay-0my/coderay-pp1) already addresses for
chapter prose: don't trust the LLM for a structural fact that's obtainable for free.

[Graphify](https://github.com/Graphify-Labs/graphify) proves the approach works -- tree-sitter
AST parsing gives calls/imports/inherits/mixes_in edges across many languages with no LLM
call, tagged `EXTRACTED` (explicit in the source) vs `INFERRED` (resolved by the tool). It
isn't adopted as a dependency here: it's a standalone CLI/knowledge-graph product (community
detection, a query/path/explain CLI, doc/PDF/media ingestion) meant to be invoked as an
assistant skill, not embedded as a library call inside a pipeline node, and it's a pre-launch
product from a very new company. The idea -- deterministic extraction, tagged confidence -- is
worth taking; the product isn't.

## Goals

- Relate's output tags each relationship `EXTRACTED` (backed by a real import edge between the
  abstractions' files) or `INFERRED` (LLM guess only).
- Works for Python, JS/TS and Go out of the box; any other language falls back to `INFERRED` only,
  never blocks or fails the run.
- Adding a new language is a small, templated addition: one grammar dependency, one extractor
  module, one registry entry -- coderay-d5f (Go) is the first consumer of this template.

## Non-goals (this iteration)

- `calls`, `inherits`, `mixes_in` edges. These need cross-file symbol resolution (whose `def
foo` does this call resolve to?), which is a materially harder, more language-specific
  problem than import resolution, and a wrong answer produces a false `EXTRACTED` tag -- worse
  than no tag. Left as a documented future extension per language module.
- Parsing files outside `shared["selected_files"]`. The budget-capped selection SmartCrawl
  already produces is the same universe Analyze and Relate operate over; walking the full
  target repo would parse files no abstraction ever references and works against the existing
  rule that per-run cost scales by capping file count, not by adding unbounded new work.
- Surfacing the tag anywhere beyond the mermaid diagram (e.g. in chapter prose or the
  Related-chapters section). Future work if the visible distinction proves useful.

## Design

### Pipeline

```text
SmartCrawl -> ExtractGraph -> Analyze -> Relate -> WriteChapters
```

One new node, inserted before Analyze so Analyze can attach a `files` field per abstraction and
validate it against the same `selected_files` list `ExtractGraph` already consumed.

### Per-language extractor template

`workflow/graph/languages/` holds one module per language:

- `python.py`, `javascript.py`, `typescript.py`, `go.py`.
  - `javascript.py` covers `.js`/`.jsx`/`.mjs`/`.cjs` with `tree_sitter_javascript`'s grammar
    (which already parses JSX syntax).
  - `typescript.py` covers both `.ts` (via `tree_sitter_typescript.language_typescript()`) and
    `.tsx` (via `tree_sitter_typescript.language_tsx()`) -- two `Language` objects in one
    module, since the package ships both grammars together.
- Each module exposes:
  - `EXTENSIONS: set[str]` -- e.g. `{".py"}`.
  - `def imports(path: str, text: str, selected_files: set[str], root: str | None = None) -> list[str]` -- parses
    `text` with that language's tree-sitter grammar, resolves each import statement to a file
    path, and returns the subset that lands inside `selected_files`. Resolution logic (Python's
    dotted-module rules vs. JS/TS relative specifiers) is entirely internal to the module; the
    function signature is the only contract shared across languages. `root` is the
    repo root, for an extractor that needs a manifest (Go reads `go.mod` for the
    module path); the others accept and ignore it.
- `workflow/graph/languages/__init__.py` builds `REGISTRY: dict[str, module]` keyed by
  extension from the modules above.
- Adding a language (coderay-d5f is the first case): add the grammar dependency to
  `pyproject.toml`, add `workflow/graph/languages/<lang>.py` implementing the two-item
  contract above, register its extensions in `REGISTRY`. No other file changes,
  unless the language needs something `ExtractGraph` does not yet pass.

New dependencies (core, not optional -- these are small, pre-built wheels, unlike the
optional LLM-provider SDKs): `tree-sitter`, `tree-sitter-python`, `tree-sitter-javascript`,
`tree-sitter-typescript`, `tree-sitter-go`.

### `ExtractGraph` node (`workflow/nodes.py`)

- `prep`: reads `shared["selected_files"]` and `shared["repo_path"]`, reads each file's text
  via `coderay_utils.safe_read` (same helper SmartCrawl already uses).
- `exec`: for each file, look up its extractor by extension in `REGISTRY`. Files with no
  registered extractor are skipped (counted, not silent). Call `imports()`, collect
  `{"from": file, "to": file, "kind": "imports"}` edges.
- `post`: `shared["symbol_graph"] = edges`; print a summary, e.g. `"6/8 selected files covered
by a deterministic import graph"`.

### Analyze schema change

`workflow/prompts/identify-abstractions.md` gains a `files` field per abstraction: the repo-
relative paths (drawn from `selected_files`) that abstraction covers. `Analyze.exec`'s
`normalize()` asserts every listed path is in `selected_files` -- same pattern as the existing
`learning_order`/`abstractions` consistency check, so a bad LLM response triggers `yaml_call`'s
existing retry-with-varied-prompt rather than a hard failure.

This mapping is still LLM-assigned (which abstraction owns which file is a judgment call, not
a structural fact), so the `EXTRACTED` tag below means "backed by a real import edge between
the files this abstraction claims" -- not "this relationship is fully verified end to end."
Worth stating explicitly wherever the tag is surfaced, so it isn't oversold.

### Relate rollup

`Relate.exec`'s `normalize()` builds `abstraction_name -> set(files)` from the new `files`
field. For each `{from, to, label}` relationship, tag `source: "EXTRACTED"` if `symbol_graph`
has an import edge whose `from` file is in the relationship's `from` abstraction's file set
_and_ whose `to` file is in the relationship's `to` abstraction's file set -- direction must
match, not either direction. An edge only in the reverse direction is evidence for the reverse
relationship, not this one; tagging it EXTRACTED here would be a wrong tag, which the error-
handling rule above already treats as worse than a missing one.

If `from` or `to` names a relationship endpoint that isn't in the abstraction file-map (the
LLM referenced an abstraction that doesn't exist -- `build_mermaid`, `workflow/__main__.py:68`,
already drops these silently downstream), the rollup has no file set to check against, so the
relationship is tagged `INFERRED` rather than asserted on: there's no structural claim to
verify, and this case is already tolerated everywhere else the relationship list is consumed.

### Output surface (`workflow/__main__.py`)

`build_mermaid` renders `EXTRACTED` edges as solid, labeled arrows (`A -- "label" --> B`, the
current form) and `INFERRED` edges as dashed, labeled arrows (`A -. "label" .-> B`, mermaid's
dashed-with-label syntax, different from the plain `-.->` unlabeled form) so the tour visibly
shows which relationships are grounded. This is a real change to `build_mermaid`, not just a
new branch -- the function needs to pick the arrow syntax per edge based on `source`.

## Error handling

- Unparseable file (syntax error, unsupported dialect, encoding issue): skip that file for
  graph purposes, never fail the run.
- Ambiguous import resolution (can't tell which of several candidate files an import targets):
  drop the edge. A missing edge is an acceptable false negative; a wrong edge is not.
- Abstraction `files` referencing a path outside `selected_files`: assertion failure, handled
  by `yaml_call`'s existing retry.

## Testing

- Per-language extractor unit tests against small fixture snippets (no network, matches
  existing `tests/` style) -- one fixture pair per language proving a real import resolves to
  an edge, and one proving an unresolvable import produces none.
- `ExtractGraph` node test with a mix of registered and unregistered extensions, asserting
  unknown extensions are skipped without failing the node.
- `Relate` rollup test with a fixed `symbol_graph` and abstraction file sets, asserting the
  `EXTRACTED`/`INFERRED` tag matches expectations in both directions.
- `workflow/flow.py` wiring updated for the new node; existing `test_main.py`/`test_nodes.py`
  fixtures updated wherever they construct the full pipeline shared state.

## Decisions

- **Imports only in v1**, not calls/inherits/mixes_in -- see Non-goals. `calls` and friends
  need per-language symbol resolution; a wrong answer there is worse than no answer.
- **Graph built over `selected_files` only**, not the full repo -- keeps this stage's cost
  bounded by the same budget every other stage already respects.
- **Per-language grammar packages** (`tree-sitter-python`, `tree-sitter-javascript`,
  `tree-sitter-typescript`) over a bundled multi-language package (`tree-sitter-language-pack`)
  -- keeps the dependency list matched exactly to supported languages, and makes "add a
  language" concretely mean "add one package."
- **Not adopting Graphify as a dependency** -- see Problem. Its EXTRACTED/INFERRED framing and
  tree-sitter-based extraction validated the approach; its product surface (graph UI, community
  detection, doc/media ingestion, CLI-first design) is unrelated to what Relate needs.
- **Grammar packages are core dependencies, not optional extras**, unlike the LLM-provider
  SDKs. Defensible at four packages (small, pre-built wheels, no native toolchain needed).
  Every added language grows the install for every user, including ones touring repos in
  languages coderay doesn't parse -- this doesn't scale forever. If the language count grows
  past what feels reasonable as a mandatory install (a handful more, roughly), revisit as an
  optional extra (e.g. `pip install coderay[graph]`) rather than assuming core dependencies
  indefinitely.
