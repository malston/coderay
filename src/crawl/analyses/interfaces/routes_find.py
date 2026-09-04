"""Find a repo's interface: the files that declare its entry points.

A route manifest is rarely named `api`; its location is a framework convention.
We collect the surface files across the common conventions:

  Rails            config/routes.rb
  Django           **/urls.py
  Express/Fastify  **/routes.ts, **/router.ts
  Next.js          **/pages/api/**/*.ts, **/app/**/route.ts   (path IS the URL)
  tRPC             **/_router.ts
  GraphQL / gRPC   **/*.graphql, **/*.proto
  Go               any .go file whose text registers handlers (test names and
                   fixture directories are skipped)

`crawl_routes` concatenates them (capped) into the `{routes}` the prompts read.
`read_files` resolves an LLM-picked list of source paths for the sequence view.
Nothing here calls an LLM.
"""
import os
import re

from crawl.core import DEFAULT_MAX_FILE_BYTES, DEFAULT_SKIP_DIR, FIXTURE_DIRS, readable

SKIP_DIRS = DEFAULT_SKIP_DIR | FIXTURE_DIRS | {'.storybook'}

_TEST_MARKERS = ('.test.', '.spec.', '_test.', '.stories.')
_ROUTE_BASENAMES = frozenset({
    'routes.rb', 'urls.py', 'routes.ts', 'router.ts', 'routes.js', 'router.js',
    'schema.graphql',
})
# A registration-shaped call in Go: a mux or router constructor (package-
# qualified, so a `func NewRouter(` definition does not count), `HandleFunc(`,
# or a method whose first argument is a path literal. A heuristic:
# `r.Header.Get("X-Token")` does not match, since its argument is not a path,
# but an HTTP client calling `.Get("/users")` does (coderay-5wu.12).
_GO_REGISTRATION = re.compile(
    r'\bHandleFunc\(|http\.NewServeMux\(|\w+\.NewRouter\(|gin\.(?:Default|New)\(|echo\.New\('
    r'|\.(?:Get|Post|Put|Delete|Patch|Options|Head|Any|GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD'
    r'|Handle|Route|Mount|Group)\(\s*"/')
_GO_LINE_COMMENT = re.compile(r'//.*')
# Go route files with at least this many registrations are manifests, read first.
_GO_MANIFEST_MIN = 5


def go_route_registrations(text):
    """Count of registration-shaped calls in a Go source file (see
    _GO_REGISTRATION), with line comments stripped so a commented-out example
    does not count."""
    return len(_GO_REGISTRATION.findall(_GO_LINE_COMMENT.sub("", text)))


def _go_candidate(rel):
    """True if a .go file may hold route registrations: any .go file not named
    like a test (`test*.go`, `*_test.go`, `*.test.*`). `latest.go` and
    `attestation.go` qualify. Fixture directories are pruned from the walk."""
    base = os.path.basename(rel)
    return (rel.endswith(".go") and not base.startswith("test")
            and not any(m in base for m in _TEST_MARKERS))


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield dirpath, dirnames, filenames


def is_route_file(rel):
    """True if `rel` (a repo-relative path) declares entry points.

    The directory conventions below are matched with their surrounding slashes,
    so the path carries a leading one: Next.js keeps `pages/api/` or `app/` at
    the repo root, which is the layout the framework generates."""
    p = "/" + rel.replace(os.sep, "/").lstrip("/")
    base = os.path.basename(p)
    if any(m in base for m in _TEST_MARKERS):
        return False
    if base in _ROUTE_BASENAMES:
        return True
    if base.endswith("_router.ts") or base.endswith(".proto") or base.endswith(".graphql"):
        return True
    if "/pages/api/" in p and p.endswith((".ts", ".js", ".tsx")):
        return True
    if "/app/" in p and base in ("route.ts", "route.js", "route.tsx"):
        return True
    return False


def _surface(repo):
    """Every surface file as (rel, text, weight), text read once with the
    containment check. Name-matched files carry weight 0; a Go file is on the
    surface only when its text registers handlers, and its weight is how many."""
    out = []
    for dirpath, _dirnames, filenames in _walk(repo):
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), repo)
            if is_route_file(rel):
                out.append((rel, _read(os.path.join(repo, rel), repo), 0))
            elif _go_candidate(rel):
                text = _read(os.path.join(repo, rel), repo)
                weight = go_route_registrations(text)
                if weight:
                    out.append((rel, text, weight))
    return out


def find_route_files(repo):
    return sorted(rel for rel, _text, _weight in _surface(repo))


def _read(path, repo=None):
    # A route file discovered by the walk may be a symlink out of the repo, and
    # its contents go into a prompt sent to a third-party LLM. read_files
    # already refuses LLM-named paths; this is the same rule at discovery time
    # (coderay-q2r.28), and the link target has to clear the credential skip
    # too (coderay-q2r.56).
    if repo is not None and not readable(repo, path):
        return ""
    try:
        if os.path.getsize(path) > DEFAULT_MAX_FILE_BYTES:
            return ""  # a generated file; the walk's own per-file cap
        return open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ""


def crawl_routes(repo, max_chars=900_000):
    """Concatenate the surface files with path headers, capped at max_chars.
    tRPC aggregators and Rails/Django manifests come first (they list many
    endpoints per file), so a cap trims single Next.js handlers, not the map.
    A Go file with _GO_MANIFEST_MIN or more registrations is a manifest too and
    is read ahead of the name-matched ones, busiest first."""
    surface = _surface(repo)

    def priority(rel, weight):
        base = os.path.basename(rel)
        if base in _ROUTE_BASENAMES or base.endswith(("_router.ts", ".proto", ".graphql")):
            return 0  # aggregators / manifests first
        if weight >= _GO_MANIFEST_MIN:
            return 0  # a Go file registering many routes is the manifest
        return 1

    # Manifests first, the busiest Go manifest ahead of the rest; single
    # handlers in name order, whatever language they are in.
    surface.sort(key=lambda e: (priority(e[0], e[2]), -e[2] if e[2] >= _GO_MANIFEST_MIN else 0, e[0]))
    files = [rel for rel, _text, _weight in surface]
    parts, total, kept = [], 0, []
    for rel, text, _weight in surface:
        if not text.strip():
            continue
        block = f"{'=' * 60}\nFile: {rel}\n{'=' * 60}\n{text}\n"
        if total + len(block) > max_chars:
            continue
        parts.append(block)
        total += len(block)
        kept.append(rel)
    # `kept` is the list, not a count, so the caller can report what actually
    # reached the bundle rather than what was merely found (coderay-q2r.24).
    return "\n".join(parts), files, kept


def _within(repo, full):
    """True if `full` resolves inside `repo`, symlinks followed, and a symlink
    does not rename a credential file (coderay-q2r.56).

    Delegates to crawl.core.readable, which all three crawlers share; this
    module keeps the name because read_files reads better with it. The
    containment seam is coderay's, not the port source's (coderay-q2r.16 for
    LLM-named paths, coderay-q2r.28 for discovery)."""
    return readable(repo, full)


def _ends_at_segment(path, key):
    """True if `key` is `path` or a whole trailing run of its segments."""
    return path == key or path.endswith("/" + key)


def read_files(repo, paths, max_chars=120_000, max_files=8):
    """Read an LLM-picked list of source paths for the sequence-diagram view.

    Resolves each path exactly if it exists, else by a suffix match against the
    repo (the model often gives a path that's right but for a leading dir). The
    suffix must start at a path segment, so `env` cannot resolve to `.env.example`
    and a one-letter tail cannot pick an unrelated file (coderay-q2r.61).

    `paths` is model output and the model has been reading the target repo's own
    untrusted files, so a path that leaves the repo is refused rather than read.
    A leading slash was already stripped upstream, which neutralises an absolute
    path; `_within` adds the rest, refusing `../` climbs and symlinks that
    resolve outside the repo (coderay-q2r.16).

    Returns (text, resolved, skipped). `skipped` is every named path that was
    not read, in the order named, whatever the reason: not found, empty,
    past `max_files`, over `max_chars`, or refused. The card that reports the
    diagram's provenance needs that list, and only this function knows why a
    path was left out (coderay-5wu.1)."""
    index = None
    resolved, skipped, parts, total = [], [], [], 0
    budget_spent = False
    for n, raw in enumerate(paths):
        rel = raw.strip().strip("`").lstrip("/")
        if n >= max_files or budget_spent:
            skipped.append(rel)
            continue
        full = os.path.join(repo, rel)
        if os.path.isfile(full) and not _within(repo, full):
            skipped.append(rel)
            continue
        if not os.path.isfile(full):
            if index is None:
                index = []
                for dp, dn, fn in _walk(repo):
                    dn[:] = dn  # already filtered by _walk
                    for f in fn:
                        index.append(os.path.relpath(os.path.join(dp, f), repo))
            key = rel.replace(os.sep, "/")
            match = next((r for r in index if _ends_at_segment(r.replace(os.sep, "/"), key)), None)
            if not match or not _within(repo, os.path.join(repo, match)):
                skipped.append(rel)
                continue
            full, rel = os.path.join(repo, match), match
        text = _read(full)
        if not text.strip():
            skipped.append(rel)
            continue
        block = f"{'=' * 60}\nFile: {rel}\n{'=' * 60}\n{text[:40_000]}\n"
        if total + len(block) > max_chars:
            budget_spent = True
            skipped.append(rel)
            continue
        resolved.append(rel)
        parts.append(block)
        total += len(block)
    return "\n".join(parts), resolved, skipped
