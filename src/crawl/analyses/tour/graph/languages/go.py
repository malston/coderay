"""Deterministic import extraction for Go, via tree-sitter.

Go imports name a package, which is a directory, so one import yields an edge
to every selected .go file in that directory. The repo's own packages are the
import paths under the module path declared in go.mod at the repo root:
`github.com/acme/app/pkg/types` under module `github.com/acme/app` is
`pkg/types/`. Standard-library and third-party paths sit outside the module
path and are dropped. Without a usable go.mod there is no way to tell the two
apart, so no edges are extracted and one note says so. Only import edges are
extracted (see docs/superpowers/specs/2026-08-31-deterministic-import-graph-design.md,
Non-goals).
"""
import functools
import os

import tree_sitter_go as _ts_go
from tree_sitter import Language, Parser, Query, QueryCursor

EXTENSIONS = {".go"}

_LANGUAGE = Language(_ts_go.language())

# Both string forms: gofmt writes interpreted literals, but a raw one is legal.
_IMPORT_QUERY_SRC = """
(import_spec
  path: (_) @path)
"""


@functools.lru_cache(maxsize=None)
def module_path(root):
    """The module path declared in <root>/go.mod, or None when the file or the
    `module` directive is absent.

    Accepts every form the go command does: a trailing `//` comment, a quoted
    path, and the factored `module (` block. Read once per root, since every
    Go file in the repo asks; a repo without a module path is reported once."""
    if not root:
        return None
    try:
        with open(os.path.join(root, "go.mod"), encoding="utf-8", errors="replace") as fh:
            lines = [line.split("//", 1)[0].strip() for line in fh]
    except OSError:
        return None
    found = None
    for i, line in enumerate(lines):
        fields = line.split()
        if fields[:1] != ["module"]:
            continue
        if len(fields) >= 2 and fields[1] != "(":
            found = fields[1]
        else:
            found = next((l.split()[0] for l in lines[i + 1:] if l and l != ")"), None)
        break
    if found:
        return found.strip('"')
    print(f"  no module path in go.mod under {root}: no Go import edges")
    return None


def _package_dirs(selected_files):
    """Directory -> its selected .go files, with "/" separators for matching."""
    dirs = {}
    for f in selected_files:
        if f.endswith(".go"):
            dirs.setdefault(os.path.dirname(f).replace(os.sep, "/"), []).append(f)
    return dirs


def _candidates(import_path, importer_path, module, package_dirs):
    """The selected .go files in the package `import_path` names inside this
    module, or [] when the path is outside the module, has no selected files,
    or is the importer's own package."""
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
    # Source order, so the edge list is stable run to run.
    for node in sorted(captures.get("path", []), key=lambda n: n.start_byte):
        import_path = node.text.decode("utf-8").strip('"`')
        for candidate in _candidates(import_path, path, module, package_dirs):
            if candidate not in targets:
                targets.append(candidate)
    return targets
