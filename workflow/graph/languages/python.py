"""Deterministic import extraction for Python, via tree-sitter.

Only import edges are extracted -- resolving a call target to its defining symbol
needs full name resolution, which is out of scope for v1 (see
docs/superpowers/specs/2026-08-31-deterministic-import-graph-design.md, Non-goals).
"""
import tree_sitter_python as _ts_python
from tree_sitter import Language, Parser, Query, QueryCursor

EXTENSIONS = {".py"}

_LANGUAGE = Language(_ts_python.language())

_IMPORT_QUERY_SRC = """
(import_statement
  name: (dotted_name) @module)
(import_from_statement
  module_name: (dotted_name) @module)
"""


def _candidates(module_dotted, selected_files):
    """`foo.bar` -> the repo-relative paths it could resolve to: foo/bar.py or
    foo/bar/__init__.py -- whichever is actually in selected_files."""
    base = module_dotted.replace(".", "/")
    return sorted({f"{base}.py", f"{base}/__init__.py"} & selected_files)


def imports(path, text, selected_files):
    parser = Parser(_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    query = Query(_LANGUAGE, _IMPORT_QUERY_SRC)
    captures = QueryCursor(query).captures(tree.root_node)
    targets = []
    for node in captures.get("module", []):
        module_dotted = node.text.decode("utf-8")
        for candidate in _candidates(module_dotted, selected_files):
            if candidate not in targets:
                targets.append(candidate)
    return targets
