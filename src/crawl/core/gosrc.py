"""Read Go source the way Go does, far enough to tell comments and string
literals from code.

Two crawlers need this: the interfaces surface counts route registrations and
must not count a commented-out one, and the schema crawler pulls DDL out of
string literals and must not be thrown off by a backtick in a comment or a
rune literal. A regex over the raw text gets both wrong; one scanner gets both
right, so it lives here once.
"""
import functools
import os

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', "'": "'", '`': '`'}


def _scan(text):
    """Yield (kind, value): ('code', chunk) for source outside comments and
    strings, ('string', content) for an interpreted or raw string with escapes
    resolved. Comments and rune literals are consumed and yield nothing."""
    i, n, code = 0, len(text), []
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == "'":
            j = i + 1
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        elif c == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            if code:
                yield "code", "".join(code); code = []
            yield "string", text[i + 1:j]
            i = j + 1
        elif c == '"':
            j, out = i + 1, []
            while j < n and text[j] not in '"\n':
                if text[j] == "\\" and j + 1 < n:
                    out.append(_ESCAPES.get(text[j + 1], text[j + 1])); j += 2
                else:
                    out.append(text[j]); j += 1
            if code:
                yield "code", "".join(code); code = []
            yield "string", "".join(out)
            i = j + 1
        else:
            code.append(c); i += 1
    if code:
        yield "code", "".join(code)


def string_literals(text):
    """Every string literal's content, in source order, escapes resolved."""
    return [v for k, v in _scan(text) if k == "string"]


def without_comments(text):
    """The source with comments removed and every string literal kept whole and
    quoted, so a pattern over it sees code and strings but never a comment."""
    return "".join(v if k == "code" else '"' + v + '"' for k, v in _scan(text))


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
    print(f"  no go.mod or module path under {root}")
    return None
