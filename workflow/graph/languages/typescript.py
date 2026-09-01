"""Deterministic import extraction for TypeScript and TSX, via tree-sitter.

tree-sitter-typescript ships two grammars in one package: language_typescript()
for .ts, language_tsx() for .tsx (TSX syntax isn't valid under the plain
TypeScript grammar). Both use the same import-statement query shape.
"""
import os

import tree_sitter_typescript as _ts_ts
from tree_sitter import Language, Parser, Query, QueryCursor

EXTENSIONS = {".ts", ".tsx"}

_TS_LANGUAGE = Language(_ts_ts.language_typescript())
_TSX_LANGUAGE = Language(_ts_ts.language_tsx())

_IMPORT_QUERY_SRC = """
(import_statement
  source: (string (string_fragment) @specifier))
"""

_EXTENSIONLESS_CANDIDATES = (".ts", ".tsx", "/index.ts", "/index.tsx")


def _language_for(path):
    return _TSX_LANGUAGE if path.endswith(".tsx") else _TS_LANGUAGE


def _candidates(specifier, importer_path, selected_files):
    """Resolve a relative specifier to the repo-relative path it imports. If more
    than one candidate matches selected_files, the import is ambiguous, so the
    edge is dropped rather than guessed."""
    if not specifier.startswith("."):
        return []
    importer_dir = os.path.dirname(importer_path)
    resolved_base = os.path.normpath(os.path.join(importer_dir, specifier))
    out = []
    if resolved_base in selected_files:
        out.append(resolved_base)
    for suffix in _EXTENSIONLESS_CANDIDATES:
        candidate = resolved_base + suffix if not resolved_base.endswith(suffix) else resolved_base
        if candidate in selected_files and candidate not in out:
            out.append(candidate)
    return out if len(out) <= 1 else []


def imports(path, text, selected_files):
    language = _language_for(path)
    parser = Parser(language)
    tree = parser.parse(text.encode("utf-8"))
    query = Query(language, _IMPORT_QUERY_SRC)
    captures = QueryCursor(query).captures(tree.root_node)
    targets = []
    for node in captures.get("specifier", []):
        specifier = node.text.decode("utf-8")
        for candidate in _candidates(specifier, path, selected_files):
            if candidate not in targets:
                targets.append(candidate)
    return targets
