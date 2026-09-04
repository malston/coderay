"""Deterministic import extraction for Go, via tree-sitter.

Go imports name a package, which is a directory, so one import yields an edge
to every selected file in that directory. The repo's own packages are the
import paths under the module path declared in go.mod at the repo root:
`github.com/acme/app/pkg/types` under module `github.com/acme/app` is
`pkg/types/`. Standard-library and third-party paths sit outside the module
path and are dropped. Without a go.mod there is no way to tell the two apart,
so no edges are extracted. Only import edges are extracted (see the Python
extractor for the Non-goals rationale this shares).
"""
import os
import re

import tree_sitter_go as _ts_go
from tree_sitter import Language, Parser, Query, QueryCursor

EXTENSIONS = {".go"}

_LANGUAGE = Language(_ts_go.language())

_IMPORT_QUERY_SRC = """
(import_spec
  path: (interpreted_string_literal) @path)
"""

_MODULE_LINE = re.compile(r"^module\s+(\S+)\s*$", re.M)


def module_path(root):
    """The module path declared in <root>/go.mod, or None."""
    if not root:
        return None
    try:
        with open(os.path.join(root, "go.mod"), encoding="utf-8") as fh:
            m = _MODULE_LINE.search(fh.read())
    except OSError:
        return None
    return m.group(1) if m else None


def _package_dirs(selected_files):
    """Directory -> its selected .go files, with "/" separators for matching."""
    dirs = {}
    for f in selected_files:
        if f.endswith(".go"):
            dirs.setdefault(os.path.dirname(f).replace(os.sep, "/"), []).append(f)
    return dirs


def _candidates(import_path, importer_path, module, package_dirs):
    """The selected files in the package `import_path` names inside this module,
    or [] when the path is outside the module, has no selected files, or is the
    importer's own package."""
    if import_path == module:
        rel = ""
    elif import_path.startswith(module + "/"):
        rel = import_path[len(module) + 1:]
    else:
        return []
    if rel == os.path.dirname(importer_path).replace(os.sep, "/"):
        return []
    return sorted(package_dirs.get(rel, []))


def imports(path, text, selected_files, root=None):
    module = module_path(root)
    if not module:
        return []
    parser = Parser(_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    query = Query(_LANGUAGE, _IMPORT_QUERY_SRC)
    captures = QueryCursor(query).captures(tree.root_node)
    package_dirs = _package_dirs(selected_files)
    targets = []
    for node in captures.get("path", []):
        import_path = node.text.decode("utf-8").strip('"')
        for candidate in _candidates(import_path, path, module, package_dirs):
            if candidate not in targets:
                targets.append(candidate)
    return targets
