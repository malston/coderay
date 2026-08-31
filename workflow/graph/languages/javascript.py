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

_EXTENSIONLESS_CANDIDATES = (".js", ".jsx", ".mjs", ".cjs", "/index.js", "/index.jsx")


def _candidates(specifier, importer_path, selected_files):
    if not specifier.startswith("."):
        return []  # bare package specifier, not a file in this repo
    importer_dir = os.path.dirname(importer_path)
    resolved_base = os.path.normpath(os.path.join(importer_dir, specifier))
    out = []
    if resolved_base in selected_files:
        out.append(resolved_base)
    for suffix in _EXTENSIONLESS_CANDIDATES:
        candidate = resolved_base + suffix if not resolved_base.endswith(suffix) else resolved_base
        if candidate in selected_files and candidate not in out:
            out.append(candidate)
    return out


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
