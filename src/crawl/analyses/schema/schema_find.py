"""Find and read a repo's schema, plus its migration history.

The schema is almost never a file literally called `schema`. Most repos
follow one of a few conventions, so we look for them in priority order:

  Prisma (Node/TS)     packages/**/schema.prisma        one typed DSL file
  Rails (Ruby)         db/schema.rb                     one auto-generated file
  Raw SQL              schema.sql                        one dumped file
  Django / SQLAlchemy  **/models.py                      classes, many files
  Go                   **/*.go                           DDL inside string literals, many files

`find_schema` returns the single most-schema-like text it can (concatenating the
Django/SQLAlchemy model files, or the DDL out of the Go files, when there's no
single-file schema). `find_migrations` returns the timestamped migration names,
the chronological record MigrationActs mines.

Everything here is plain filesystem walking; nothing calls an LLM.
"""
import os
import re

from crawl.core import DEFAULT_MAX_FILE_BYTES, DEFAULT_SKIP_DIR, is_test_file, readable
from crawl.core.gosrc import string_literals

# Directories that never hold a schema: the shared skip set, which does not
# prune `migrations`, the one directory this crawler must find.
SKIP_DIRS = DEFAULT_SKIP_DIR

# Prisma and Rails use 14-digit timestamps; Django numbers its migrations
# 0001_, 0002_, ... Requiring six digits matched the first two and silently
# dropped every Django history (coderay-q2r.21).
# The schema is embedded in the tour prompt, the flows prompt and EVERY
# deep-dive batch, so its size is multiplied by the run. Whole files are kept
# and the file count is capped -- never a per-file floor raised, which inverted
# the same budget twice before (coderay-q2r.29).
SCHEMA_BUDGET = 600_000

TIMESTAMP_RE = re.compile(r'^\d{4,}[_-]')  # 20210605225044_init, 0001_initial, ...

# A Go service often keeps its schema as DDL inside string literals and migrates
# in code (coderay-5wu.13). A literal is schema when it begins with a DDL
# statement; an error message that mentions creating a table is prose. The Go
# around the literals is not the schema, and neither is a comment or a rune.
_DDL_STATEMENT = re.compile(
    r'^\s*(?:CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?\w+[`"\]]?\s*\('
    r'|CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?\w+[`"\]]?\s+ON\b'
    r'|ALTER\s+TABLE\s+[`"\[]?\w+[`"\]]?\s+(?:ADD|DROP|RENAME|ALTER|MODIFY)\b)', re.I)
_CREATE_TABLE = re.compile(r'\bCREATE\s+TABLE\b', re.I)
_DDL_HINT = ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX")
MAX_SCHEMA_FILES = 40


def embedded_sql(go_text):
    """The string literals of a Go source file that begin with a DDL statement
    (CREATE TABLE, CREATE INDEX, ALTER TABLE), escapes resolved and joined, or
    "" when none do."""
    return "\n".join(lit.strip() for lit in string_literals(go_text) if _DDL_STATEMENT.match(lit))


def _join_within_budget(blocks, marker):
    """Concatenate (rel, text) blocks under SCHEMA_BUDGET, whole blocks and fewer
    of them rather than shorter ones (coderay-q2r.29); `marker` is the target
    language's comment lead so the model reads the header as a comment.
    Returns (text, kept_rels)."""
    parts, total, kept = [], 0, []
    for rel, text in blocks[:MAX_SCHEMA_FILES]:
        block = f"{marker} ===== {rel} =====\n{text}"
        if total + len(block) > SCHEMA_BUDGET and parts:
            break
        parts.append(block)
        total += len(block)
        kept.append(rel)
    return "\n\n".join(parts), kept


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield dirpath, dirnames, filenames


def _read(path, repo=None, limit=None):
    # The schema file may be a symlink out of the target repo, and it is
    # embedded in the tour prompt, the flows prompt and every deep-dive batch
    # (coderay-q2r.28), and a symlink to an in-repo credential file is refused
    # by its target name (coderay-q2r.56).
    if repo is not None and not readable(repo, path):
        return ""
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ""
    if limit is not None and len(text) > limit:
        return text[:limit] + f"\n\n# ===== TRUNCATED at {limit:,} chars =====\n"
    return text


def find_schema(repo, override=None):
    """Return {kind, path(s), text}. `override` forces a specific file."""
    if override:
        # No containment check: --schema is the user pointing at their own file,
        # and an absolute path is an advertised feature of the flag. Unlike a
        # path the crawl or the model produced, this one is not untrusted input.
        p = override if os.path.isabs(override) else os.path.join(repo, override)
        return {"kind": "override", "path": os.path.relpath(p, repo),
                "text": _read(p, limit=SCHEMA_BUDGET)}

    prisma, rails, sql, models, go_files = [], [], [], [], []
    for dirpath, _dirnames, filenames in _walk(repo):
        for f in filenames:
            full = os.path.join(dirpath, f)
            if f == "schema.prisma":
                prisma.append(full)
            elif f == "schema.rb" and os.path.basename(dirpath) == "db":
                rails.append(full)
            elif f == "schema.sql":
                sql.append(full)
            elif f == "models.py":
                models.append(full)
            elif f.endswith(".go") and not is_test_file(f):
                go_files.append(full)

    if prisma:
        # Prefer the largest schema.prisma (the app's, not a package fixture).
        path = max(prisma, key=lambda p: os.path.getsize(p))
        return {"kind": "prisma", "path": os.path.relpath(path, repo),
                "text": _read(path, repo, SCHEMA_BUDGET)}
    if rails:
        path = rails[0]
        return {"kind": "rails", "path": os.path.relpath(path, repo),
                "text": _read(path, repo, SCHEMA_BUDGET)}
    if sql:
        path = max(sql, key=lambda p: os.path.getsize(p))
        return {"kind": "sql", "path": os.path.relpath(path, repo),
                "text": _read(path, repo, SCHEMA_BUDGET)}
    if models:
        # No single-file schema: concatenate the model files (Django/SQLAlchemy).
        models = sorted(models, key=lambda p: os.path.getsize(p), reverse=True)
        text, kept = _join_within_budget(
            [(os.path.relpath(m, repo), _read(m, repo, SCHEMA_BUDGET)) for m in models], "#")
        note = "" if len(kept) == len(models) else f" of {len(models)} found"
        return {"kind": "models", "path": f"{len(kept)} models.py files{note}", "text": text}

    # Go, last: a models.py is a convention, DDL inside string literals is a
    # heuristic, and reading every Go file is the costly part, so it only
    # happens when nothing else was found. A file over the per-file cap is a
    # generated one and is not read.
    embedded = []
    for full in go_files:
        try:
            if os.path.getsize(full) > DEFAULT_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        text = _read(full, repo)
        if not any(hint in text.upper() for hint in _DDL_HINT):
            continue
        ddl = embedded_sql(text)
        if ddl:
            embedded.append((len(_CREATE_TABLE.findall(ddl)), full, ddl))
    if embedded:
        # The file creating the most tables first; a file of ALTERs follows,
        # since the columns it adds are part of the schema too.
        embedded.sort(key=lambda e: (-e[0], e[1]))
        text, kept = _join_within_budget([(os.path.relpath(full, repo), ddl) for _c, full, ddl in embedded], "--")
        note = "" if len(kept) == len(embedded) else f" of {len(embedded)} found"
        return {"kind": "embedded-sql",
                "path": f"{len(kept)} Go files with embedded SQL ({', '.join(kept)}){note}",
                "text": text}

    return {"kind": None, "path": None, "text": ""}


def find_migrations(repo):
    """Return (dir_relpath, [names oldest-first]) for the repo's migration history.

    Handles Prisma (a `migrations/` dir of timestamped subfolders), Rails
    (`db/migrate/*.rb`), Django (`**/migrations/0*.py`), and the goose and
    golang-migrate `.sql` layouts, counting an up/down pair once. Picks the
    migration directory with the most timestamped entries."""
    best = None  # (count, reldir, names)
    for dirpath, _dirnames, filenames in _walk(repo):
        base = os.path.basename(dirpath)
        if base not in ("migrations", "migrate"):
            continue
        entries = sorted(os.listdir(dirpath))
        names = [e for e in entries if TIMESTAMP_RE.match(e)]
        # Prisma: subdirs. Rails/Django: files. Strip a file extension for display.
        names = [os.path.splitext(n)[0] if "." in n else n for n in names]
        # golang-migrate: 000001_init.up.sql and .down.sql are one migration.
        names = [n[:-3] if n.endswith(".up") else n for n in names if not n.endswith(".down")]
        names = [n for n in names if n and not n.startswith("__")]
        if len(names) > (best[0] if best else 0):
            best = (len(names), os.path.relpath(dirpath, repo), names)
    if not best:
        return None, []
    return best[1], best[2]
