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

from crawl.core import DEFAULT_MAX_FILE_BYTES, DEFAULT_SKIP_DIR, is_test_file, readable
from crawl.core.gosrc import without_comments

SKIP_DIRS = DEFAULT_SKIP_DIR | {'.storybook'}
_ROUTE_BASENAMES = frozenset({
    'routes.rb', 'urls.py', 'routes.ts', 'router.ts', 'routes.js', 'router.js',
    'schema.graphql',
})
# What builds a server in Go: a mux, router or gRPC server constructor
# (package-qualified, so a `func NewRouter(` definition does not count) or
# `HandleFunc(`. A file that builds one and registers _GO_MANIFEST_MIN or more
# routes is a manifest; a typed HTTP client never builds one, so its
# `.Get("/users")` calls count as registrations but cannot make it a manifest.
_GO_BUILDS_SERVER = re.compile(
    r'\bHandleFunc\(|http\.NewServeMux\(|\w+\.NewRouter\(|gin\.(?:Default|New)\(|echo\.New\('
    r'|grpc\.NewServer\(')
# A registration-shaped call: a server being built, a method whose first
# argument is a path literal (or a Go 1.22 "METHOD /path" pattern), a gorilla
# .Path("/..") chain, or a gRPC RegisterXServer call. A heuristic:
# `r.Header.Get("X-Token")` does not match, since its argument is not a path,
# but an HTTP client calling `.Get("/users")` does (coderay-5wu.12).
_GO_REGISTRATION = re.compile(
    _GO_BUILDS_SERVER.pattern
    + r'|\bRegister\w+Server\(|\.Path\(\s*"/'
    + r'|\.(?:Get|Post|Put|Delete|Patch|Options|Head|Any|GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD'
    + r'|Handle|Route|Mount|Group)\(\s*"(?:[A-Z]+ )?/')
# What a serving entry point mentions when the heuristic above finds none of
# its registrations: the listener it starts.
_GO_SERVES = re.compile(r'"net/http"|ListenAndServe|grpc\.NewServer|\.Serve\(|\.Run\(')
# Go route files that build a server and register at least this many routes
# are manifests, read first.
_GO_MANIFEST_MIN = 5


def go_route_registrations(text):
    """Count of registration-shaped calls in a Go source file (see
    _GO_REGISTRATION), with comments removed by the shared Go scanner so a
    commented-out example does not count and a URL's // is not a comment."""
    return len(_GO_REGISTRATION.findall(without_comments(text)))


def _go_manifest(text, weight):
    return weight >= _GO_MANIFEST_MIN and bool(_GO_BUILDS_SERVER.search(text))


def _go_candidate(rel):
    """True if a .go file may hold route registrations: any .go file that is not
    test scaffolding by name (crawl.core.is_test_file). `latest.go`,
    `attestation.go` and `testimonials.go` qualify; fixture directories are
    pruned from the walk."""
    return rel.endswith(".go") and not is_test_file(os.path.basename(rel))


def _is_manifest_name(base):
    """A name that marks a file as a route manifest: it lists many endpoints."""
    return base in _ROUTE_BASENAMES or base.endswith(("_router.ts", ".proto", ".graphql"))


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
    if is_test_file(base):
        return False
    if _is_manifest_name(base):
        return True
    if "/pages/api/" in p and p.endswith((".ts", ".js", ".tsx")):
        return True
    if "/app/" in p and base in ("route.ts", "route.js", "route.tsx"):
        return True
    return False


def _surface(repo):
    """Every surface file as (rel, text, manifest), text read once with the
    containment check. A name-matched file is a manifest when its name says so;
    a Go file is on the surface only when its text registers handlers, and is
    a manifest when it also builds a server and registers _GO_MANIFEST_MIN or
    more (the count breaks ties among Go manifests, so `manifest` carries it as
    a negative weight). A Go file over the shared per-file cap is a generated
    one and is not scanned. When a repo has Go source and no file registers
    anything the heuristic knows, a cmd/*/main.go that starts a listener
    stands in as the entry point, so a code-generated or constant-path router
    does not leave the surface empty; a CLI's main.go does not qualify."""
    out, go_hits, go_mains = [], 0, []
    for dirpath, _dirnames, filenames in _walk(repo):
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), repo)
            full = os.path.join(repo, rel)
            if is_route_file(rel):
                out.append((rel, _read(full, repo), 0 if _is_manifest_name(f) else None))
            elif _go_candidate(rel):
                if "/cmd/" in "/" + rel.replace(os.sep, "/") and f == "main.go":
                    go_mains.append(rel)
                try:
                    if os.path.getsize(full) > DEFAULT_MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                text = _read(full, repo)
                weight = go_route_registrations(text)
                if weight:
                    go_hits += 1
                    out.append((rel, text, -weight if _go_manifest(text, weight) else None))
                elif rel in go_mains and _GO_SERVES.search(text):
                    go_mains[go_mains.index(rel)] = (rel, text)
    if not go_hits:
        out.extend((rel, text, None) for entry in go_mains if isinstance(entry, tuple) for rel, text in [entry])
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
        return open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ""


def crawl_routes(repo, max_chars=900_000):
    """Concatenate the surface files with path headers, capped at max_chars.
    tRPC aggregators and Rails/Django manifests come first (they list many
    endpoints per file), so a cap trims single Next.js handlers, not the map.
    A Go file that builds a server and registers _GO_MANIFEST_MIN or more
    routes is a manifest too, read after the name-matched ones (a name is
    certain, a count is a heuristic), busiest first."""
    surface = _surface(repo)

    def order(entry):
        rel, _text, manifest = entry
        if manifest == 0:
            return (0, 0, rel)         # name-matched manifest: a name is certain
        if manifest is not None:
            return (1, manifest, rel)  # Go manifest, busiest first (negative weight)
        return (2, 0, rel)             # single handlers, name order, any language

    surface.sort(key=order)
    files = [rel for rel, _text, _manifest in surface]
    parts, total, kept = [], 0, []
    for rel, text, _manifest in surface:
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
    """True if `full` resolves inside `repo`, symlinks followed, and the
    resolved target's own name is not credential-bearing -- whether the model
    named `.env` outright or a symlink inside the repo resolves to one
    (coderay-q2r.56).

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
