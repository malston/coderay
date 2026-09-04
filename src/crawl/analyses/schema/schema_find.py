"""Find and read a repo's schema, plus its migration history.

The schema is almost never a file literally called `schema`. Most repos
follow one of a few conventions, so we look for them in priority order:

  Prisma (Node/TS)     packages/**/schema.prisma        one typed DSL file
  Rails (Ruby)         db/schema.rb                     one auto-generated file
  Raw SQL              schema.sql                        one dumped file
  Django / SQLAlchemy  **/models.py                      classes, many files
  Go                   CREATE TABLE inside .go string literals, many files

`find_schema` returns the single most-schema-like text it can (concatenating the
Django/SQLAlchemy model files when there's no single-file schema). `find_migrations`
returns the timestamped migration names, the chronological record MigrationActs mines.

Everything here is plain filesystem walking; nothing calls an LLM.
"""
import os
import re

from crawl.core import DEFAULT_SKIP_DIR, FIXTURE_DIRS, readable

# Directories that never hold a schema: the shared skip set, which does not
# prune `migrations`, the one directory this crawler must find.
SKIP_DIRS = DEFAULT_SKIP_DIR | FIXTURE_DIRS

# Prisma and Rails use 14-digit timestamps; Django numbers its migrations
# 0001_, 0002_, ... Requiring six digits matched the first two and silently
# dropped every Django history (coderay-q2r.21).
# The schema is embedded in the tour prompt, the flows prompt and EVERY
# deep-dive batch, so its size is multiplied by the run. Whole files are kept
# and the file count is capped -- never a per-file floor raised, which inverted
# the same budget twice before (coderay-q2r.29).
SCHEMA_BUDGET = 600_000
MAX_MODEL_FILES = 40

TIMESTAMP_RE = re.compile(r'^\d{4,}[_-]')  # 20210605225044_init, 0001_initial, ...

# A Go service often keeps its schema as DDL inside string literals and migrates
# in code (coderay-5wu.13). The literals that carry DDL are the schema; the Go
# around them is not.
_GO_STRING = re.compile(r'`[^`]*`|"(?:[^"\\\n]|\\.)*"')
_DDL = re.compile(r'\b(?:CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)|ALTER\s+TABLE)\b', re.I)
_CREATE_TABLE = re.compile(r'\bCREATE\s+TABLE\b', re.I)
MAX_EMBEDDED_FILES = 40


def embedded_sql(go_text):
    """The DDL statements a Go source file holds in its string literals, joined,
    or "" when it holds none."""
    return "\n".join(lit.strip('`"').strip() for lit in _GO_STRING.findall(go_text) if _DDL.search(lit))


def _go_candidate(filename):
    return filename.endswith(".go") and not filename.endswith("_test.go") and not filename.startswith("test")


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

    prisma, rails, sql, models, embedded = [], [], [], [], []
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
            elif _go_candidate(f):
                ddl = embedded_sql(_read(full, repo))
                if _CREATE_TABLE.search(ddl):
                    embedded.append((len(_CREATE_TABLE.findall(ddl)), full, ddl))

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
    if embedded:
        # Go: the DDL out of each file's string literals, the file creating the
        # most tables first. Whole files, fewer of them, as for models below.
        embedded.sort(key=lambda e: (-e[0], e[1]))
        parts, total, kept = [], 0, []
        for _count, full, ddl in embedded[:MAX_EMBEDDED_FILES]:
            rel = os.path.relpath(full, repo)
            block = f"-- ===== {rel} =====\n{ddl}"
            if total + len(block) > SCHEMA_BUDGET and parts:
                break
            parts.append(block)
            total += len(block)
            kept.append(rel)
        note = "" if len(kept) == len(embedded) else f" of {len(embedded)} found"
        return {"kind": "embedded-sql",
                "path": f"{len(kept)} Go file{'s' if len(kept) != 1 else ''} with embedded SQL ({', '.join(kept)}){note}",
                "text": "\n\n".join(parts)}
    if models:
        # No single-file schema: concatenate the model files (Django/SQLAlchemy).
        models = sorted(models, key=lambda p: os.path.getsize(p), reverse=True)[:MAX_MODEL_FILES]
        # Whole files, fewer of them: stop adding once the budget is spent
        # rather than shortening each one (coderay-q2r.29).
        parts, total, kept = [], 0, 0
        for m in models:
            block = f"# ===== {os.path.relpath(m, repo)} =====\n{_read(m, repo, SCHEMA_BUDGET)}"
            if total + len(block) > SCHEMA_BUDGET and parts:
                break
            parts.append(block)
            total += len(block)
            kept += 1
        note = "" if kept == len(models) else f" of {len(models)} found"
        return {"kind": "models", "path": f"{kept} models.py files{note}",
                "text": "\n\n".join(parts)}

    return {"kind": None, "path": None, "text": ""}


def find_migrations(repo):
    """Return (dir_relpath, [names oldest-first]) for the repo's migration history.

    Handles Prisma (a `migrations/` dir of timestamped subfolders), Rails
    (`db/migrate/*.rb`), and Django (`**/migrations/0*.py`). Picks the migration
    directory with the most timestamped entries."""
    best = None  # (count, reldir, names)
    for dirpath, _dirnames, filenames in _walk(repo):
        base = os.path.basename(dirpath)
        if base not in ("migrations", "migrate"):
            continue
        entries = sorted(os.listdir(dirpath))
        names = [e for e in entries if TIMESTAMP_RE.match(e)]
        # Prisma: subdirs. Rails/Django: files. Strip a file extension for display.
        names = [os.path.splitext(n)[0] if "." in n else n for n in names]
        names = [n for n in names if n and not n.startswith("__")]
        if len(names) > (best[0] if best else 0):
            best = (len(names), os.path.relpath(dirpath, repo), names)
    if not best:
        return None, []
    return best[1], best[2]
