"""Read Go source the way Go does, far enough to tell comments and string
literals from code.

Two crawlers need this: the interfaces surface counts route registrations and
must not count a commented-out one, and the schema crawler pulls DDL out of
string literals and must not be thrown off by a backtick in a comment or a
rune literal. A regex over the raw text gets both wrong; one scanner gets both
right, so it lives here once.
"""

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
