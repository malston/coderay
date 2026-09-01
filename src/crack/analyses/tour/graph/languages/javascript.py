"""Deterministic import extraction for JavaScript (including JSX), via tree-sitter.

Only relative specifiers ('./foo', '../foo') resolve to a repo file -- a bare
specifier ('react', 'lodash') is a third-party package, never a file in
selected_files, so it's silently dropped (see the Python extractor for the
Non-goals rationale this shares).
"""
import os

import tree_sitter_javascript as _ts_js
from tree_sitter import Language, Parser, Query, QueryCursor

EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}

_LANGUAGE = Language(_ts_js.language())

_IMPORT_QUERY_SRC = """
(import_statement
  source: (string (string_fragment) @specifier))
"""

_EXTENSIONLESS_CANDIDATES = (".js", ".jsx", ".mjs", ".cjs")
_INDEX_CANDIDATES = (".js", ".jsx")


def _candidates(specifier, importer_path, selected_files):
    """Resolve a relative specifier to the repo-relative path it imports. If more
    than one candidate matches selected_files, the import is ambiguous, so the
    edge is dropped rather than guessed.

    A specifier that already names an extension (e.g. './x.js') is resolved by
    exact match only -- it never enters the extensionless-guessing loop below,
    so an unrelated file that happens to share a prefix (e.g. 'x.js.jsx') can't
    turn an unambiguous import into a false "ambiguous" one.
    """
    if not specifier.startswith("."):
        return []  # bare package specifier, not a file in this repo
    importer_dir = os.path.dirname(importer_path)
    resolved_base = os.path.normpath(os.path.join(importer_dir, specifier))
    if resolved_base in selected_files:
        return [resolved_base]
    if os.path.splitext(resolved_base)[1]:
        return []  # specifier already carries an extension; no guessing
    out = []
    for ext in _EXTENSIONLESS_CANDIDATES:
        candidate = resolved_base + ext
        if candidate in selected_files and candidate not in out:
            out.append(candidate)
    for ext in _INDEX_CANDIDATES:
        # os.sep, not a hardcoded "/": selected_files is built from
        # os.path.relpath, so its separator matches the running platform.
        candidate = f"{resolved_base}{os.sep}index{ext}"
        if candidate in selected_files and candidate not in out:
            out.append(candidate)
    return out if len(out) <= 1 else []


def imports(path, text, selected_files):
    parser = Parser(_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    query = Query(_LANGUAGE, _IMPORT_QUERY_SRC)
    captures = QueryCursor(query).captures(tree.root_node)
    targets = []
    for node in captures.get("specifier", []):
        specifier = node.text.decode("utf-8")
        for candidate in _candidates(specifier, path, selected_files):
            if candidate not in targets:
                targets.append(candidate)
    return targets
