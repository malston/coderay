"""Deterministic import extraction for Go, via tree-sitter.

Go imports name a package, which is a directory, so one import yields an edge
to every selected non-test .go file in that directory (a _test.go file is
never linked into the package it tests). The repo's own packages are the
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
from tree_sitter import Language

from . import capture_texts

EXTENSIONS = {".go"}

_LANGUAGE = Language(_ts_go.language())

# Both string forms: gofmt writes interpreted literals, but a raw one is legal.
_IMPORT_QUERY_SRC = """
(import_spec
  path: (_) @path)
"""


def module_path(root):
    """The module path declared in <root>/go.mod, or None when the file or the
    `module` directive is absent, in which case one note is printed per root.

    Accepts every form the go command does: a trailing `//` comment, a quoted
    path, and the factored `module (` block. Read once per root while go.mod is
    unchanged, since every Go file in the repo asks."""
    if not root:
        return None
    gomod = os.path.join(root, "go.mod")
    try:
        stamp = os.stat(gomod).st_mtime_ns
    except OSError:
        stamp = None
    return _module_path(root, gomod, stamp)


@functools.lru_cache(maxsize=None)
def _module_path(root, gomod, stamp):
    lines = []
    if stamp is not None:
        try:
            with open(gomod, encoding="utf-8", errors="replace") as fh:
                lines = [line.split("//", 1)[0].strip() for line in fh]
        except OSError:
            lines = []
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
    print(f"  no go.mod or module path under {root}: no Go import edges")
    return None


def _package_dir(path):
    return os.path.dirname(path).replace(os.sep, "/")


def _package_dirs(selected_files):
    """Directory -> its selected non-test .go files, sorted, keyed with "/"."""
    dirs = {}
    for f in sorted(selected_files):
        if f.endswith(".go") and not f.endswith("_test.go"):
            dirs.setdefault(_package_dir(f), []).append(f)
    return dirs


def _candidates(import_path, importer_path, module, package_dirs):
    """The selected files in the package `import_path` names inside this module,
    or [] when the path is outside the module, has no selected files, or is the
    importer's own package."""
    if not (import_path + "/").startswith(module + "/"):
        return []
    rel = import_path[len(module) + 1:]
    if rel == _package_dir(importer_path):
        return []
    return package_dirs.get(rel, [])


def imports(path, text, selected_files, root=None):
    module = module_path(root)
    if not module:
        return []
    package_dirs = _package_dirs(selected_files)
    targets = []
    for literal in capture_texts(_LANGUAGE, _IMPORT_QUERY_SRC, text, "path"):
        for candidate in _candidates(literal.strip('"`'), path, module, package_dirs):
            if candidate not in targets:
                targets.append(candidate)
    return targets
