"""Deterministic import extraction for Python, via tree-sitter.

Only import edges are extracted -- resolving a call target to its defining symbol
needs full name resolution, which is out of scope for v1 (see
docs/superpowers/specs/2026-08-31-deterministic-import-graph-design.md, Non-goals).
"""
import os

import tree_sitter_python as _ts_python
from tree_sitter import Language

from . import capture_texts

EXTENSIONS = {".py"}

_LANGUAGE = Language(_ts_python.language())

_IMPORT_QUERY_SRC = """
(import_statement
  name: (dotted_name) @module)
(import_from_statement
  module_name: (dotted_name) @module)
"""


def _candidates(module_dotted, selected_files):
    """`foo.bar` -> the repo-relative path it resolves to: foo/bar.py or
    foo/bar/__init__.py -- whichever is actually in selected_files. If both are
    present, the import is ambiguous, so the edge is dropped rather than guessed.

    Joins with os.sep, not a hardcoded "/": selected_files is built from
    os.path.relpath on this machine, so its separator matches whatever the
    running platform uses.
    """
    base = module_dotted.replace(".", os.sep)
    matches = sorted({f"{base}.py", f"{base}{os.sep}__init__.py"} & selected_files)
    return matches if len(matches) <= 1 else []


def imports(path, text, selected_files, root=None):
    # `root` is the repo root, for extractors that read a manifest; unused here.
    targets = []
    for module_dotted in capture_texts(_LANGUAGE, _IMPORT_QUERY_SRC, text, "module"):
        for candidate in _candidates(module_dotted, selected_files):
            if candidate not in targets:
                targets.append(candidate)
    return targets
