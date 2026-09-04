"""One import extractor per language, keyed by file extension.

Every extractor exposes EXTENSIONS and `imports(path, text, selected_files,
root=None)`; `capture_texts` is the tree-sitter scaffold they share, so a
grammar API change is patched in one place."""
from tree_sitter import Parser, Query, QueryCursor


def capture_texts(language, query_src, text, capture):
    """The decoded text of every `capture` node the query finds in `text`, in
    source order, so an extractor's edge list is stable run to run."""
    tree = Parser(language).parse(text.encode("utf-8"))
    captures = QueryCursor(Query(language, query_src)).captures(tree.root_node)
    return [node.text.decode("utf-8")
            for node in sorted(captures.get(capture, []), key=lambda n: n.start_byte)]


from . import go, javascript, python, typescript  # noqa: E402  (they import capture_texts from here)

REGISTRY = {}
for _module in (python, javascript, typescript, go):
    for _ext in _module.EXTENSIONS:
        REGISTRY[_ext] = _module
