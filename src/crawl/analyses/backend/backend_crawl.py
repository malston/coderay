"""Crawl a backend into the six layers a request flows through.

Every backend is the same six layers with different names:
  route → middleware → handler → service → database → response

We classify each source file into a layer by its path, report a file count per
layer (so the prompts can lead with a concrete number, not an adjective), and
build a bundle that leads with the 'spine' files — routing, middleware, and the
response/decorator helpers, where teams write their custom idioms — plus a
sample of the handler/service/model files. Each layer gets an equal share of
the budget, then the leftover goes round-robin. Nothing is cut part way.
Nothing calls an LLM.
"""
import os
from collections import Counter

from crawl.core import DEFAULT_SKIP_DIR, is_test_file, list_files, safe_read

# The crawler's shared noise set plus the directories a backend keeps that
# hold no request-path code (coderay-q2r.59: the port's own list missed `env`,
# `spec` and `.tox`, so a virtualenv or an RSpec tree inflated the counts).
SKIP_DIRS = DEFAULT_SKIP_DIR | {
    '.yarn', 'migrations', 'static', 'locale', 'frontend_tests', 'node_tests',
}
SRC_EXT = ('.py', '.ts', '.tsx', '.js', '.rb', '.go', '.java', '.php')
LAYERS = ('route', 'middleware', 'handler', 'service', 'database', 'response')
# Spine layers lead the bundle; the sampled layers follow.
BUNDLE_ORDER = ('route', 'middleware', 'response', 'handler', 'service', 'database')
# Files where teams most often write custom idioms.
SPINE_NAMES = ('urls.py', 'rest.py', 'response.py', 'decorator.py', 'decorators.py',
               'middleware.py', 'computed_settings.py', 'routes.rb', 'application_controller.rb')
# Core-action keywords: sample these files first so the trace has the spine endpoint.
CORE_HINTS = ('message', 'send', 'booking', 'book', 'order', 'checkout', 'create',
              'post', 'auth', 'user', 'session', 'event')


# Go has no framework layout, so its layers come from the file names and
# singular package directories a net/http service uses; these sit beside the
# directory conventions every language shares (coderay-5wu.11).
GO_ROUTE_NAMES = ('server.go', 'router.go', 'routes.go', 'mux.go')
GO_HANDLER_SUFFIXES = ('_api.go', '_handler.go', '_handlers.go')
GO_HANDLER_NAMES = ('handler.go', 'handlers.go')
GO_SERVICE_SUFFIXES = ('_service.go',)
GO_DATABASE_NAMES = ('db.go', 'database.go', 'store.go', 'queries.go')
GO_DATABASE_SUFFIXES = ('_store.go', '.sql.go', '_repository.go')
GO_RESPONSE_SUFFIXES = ('_response.go',)


def classify(rel):
    """Return the layer a file belongs to, or None.

    The directory conventions below are matched with their surrounding slashes,
    so the path carries a leading one: a repo that keeps `pages/api/` or
    `routes/` at its root reads the same as one that nests them under `src/`.
    Framework file names (Django, Rails, Node, Go) sit beside them; a Go
    `main.go` counts as the route layer only under `cmd/`, where a server's
    process starts, since a `main.go` elsewhere is a tool."""
    p = '/' + rel.replace(os.sep, '/').lower().lstrip('/')
    base = os.path.basename(p)
    if not p.endswith(SRC_EXT):
        return None
    if is_test_file(base):
        return None
    is_go = p.endswith('.go')
    # Route
    if (base in ('urls.py', 'routes.rb', 'routes.ts', 'router.ts', 'routes.js', 'router.js')
            or base.endswith('_router.ts') or '/pages/api/' in p or '/routes/' in p or '/urls/' in p
            or (is_go and (base in GO_ROUTE_NAMES or (base == 'main.go' and '/cmd/' in p)))):
        return 'route'
    # Middleware (incl. decorators and the settings file that lists MIDDLEWARE)
    if ('middleware' in p or base.endswith(('decorator.py', 'decorators.py'))
            or base in ('computed_settings.py',)):
        return 'middleware'
    # Handler
    if ('/views/' in p or '/controllers/' in p or '/handlers/' in p
            or base == 'views.py' or base.endswith(('view.py', '_views.py', 'controller.rb'))
            or (is_go and (base in GO_HANDLER_NAMES or base.endswith(GO_HANDLER_SUFFIXES) or '/handler/' in p))):
        return 'handler'
    # Service (business logic)
    if ('/actions/' in p or '/services/' in p or '/domain/' in p or '/use' in p and 'case' in p
            or (is_go and (base == 'service.go' or base.endswith(GO_SERVICE_SUFFIXES) or '/service/' in p))):
        return 'service'
    # Database
    if ('/models/' in p or base in ('models.py', 'schema.rb') or '/repositories/' in p or '/repository/' in p
            or (is_go and (base in GO_DATABASE_NAMES or base.endswith(GO_DATABASE_SUFFIXES)
                           or '/store/' in p or '/db/' in p or '/database/' in p or '/sqlc/' in p))):
        return 'database'
    # Response
    if ('serializer' in p or '/serializers/' in p or (base.startswith('response') and base.endswith('.py'))
            or (is_go and (base == 'response.go' or base.endswith(GO_RESPONSE_SUFFIXES) or '/dto/' in p))):
        return 'response'
    return None


def _block(layer, rel, text):
    return f"\n===== LAYER {layer.upper()}: {rel} =====\n{text}\n"


def _priority(rel):
    b = os.path.basename(rel).lower()
    return (0 if any(h in b for h in CORE_HINTS) else 1)


def build_bundle(repo, max_chars=650_000, per_layer_sample=18):
    files_by_layer = {k: [] for k in LAYERS}
    counts = Counter()
    # list_files carries the repo containment and credential-name checks every
    # crawler shares (coderay-q2r.54). keep_ext/keep_names are narrowed to the
    # backend's own source set because list_files applies them to a symlink's
    # target name too: with the defaults, `app/urls.py -> ../notes.md` would
    # pass and classify() would file the link as a route.
    for path in list_files(repo, keep_ext=SRC_EXT, skip_dirs=SKIP_DIRS, keep_names=frozenset()):
        rel = os.path.relpath(path, repo)
        layer = classify(rel)
        if layer:
            counts[layer] += 1
            files_by_layer[layer].append(rel)

    # Candidates per layer: every spine file; handlers/services/models ranked,
    # and sampled from the files that actually have text, so an empty or
    # undecodable file does not use up a sample slot.
    queues, limit = {}, {}
    for layer in ('route', 'middleware', 'response'):
        # A Go cmd/*/main.go is a thin entry point; the files that register
        # routes come first so a many-binary repo does not fill the route
        # share with them.
        queues[layer] = sorted(files_by_layer[layer], key=lambda r: (r.endswith('main.go'), r))
    for layer in ('handler', 'service', 'database'):
        queues[layer] = sorted(files_by_layer[layer], key=lambda r: (_priority(r), r))
        limit[layer] = per_layer_sample

    header = "===== LAYER FILE COUNTS (whole repo) =====\n" + "\n".join(
        f"{layer}: {counts[layer]} files" for layer in LAYERS) + "\n"

    # Every populated layer gets an equal share of the budget first, filled in
    # its priority order with a file that does not fit set aside whole, never
    # cut; the unspent budget then goes round-robin over what was set aside
    # (coderay-q2r.58, coderay-q2r.64). Set-aside files are kept by name and
    # size, not text, so memory stays near max_chars however large the repo. When everything fits, the selection is
    # the same as one straight pass. Emission is grouped by layer and in
    # priority order inside it, so the prompts see one layout regardless.
    # ponytail: shares are equal, so one legitimate spine file larger than a
    # share (max_chars/4 with four populated layers) is dropped; weight the
    # spine layers if that ever bites.
    populated = [layer for layer in BUNDLE_ORDER if queues[layer]]
    chosen = {layer: [] for layer in LAYERS}       # (rank, rel, block)
    set_aside = {layer: [] for layer in LAYERS}    # (rank, rel, size): read again only if chosen
    total = len(header)
    for n, layer in enumerate(populated):
        # What remains, divided by the layers still to come, so a layer that
        # underspends its share, or is populated by empty files alone, hands
        # the difference forward.
        share = (max_chars - total) // (len(populated) - n)
        spent = 0
        for rank, rel in enumerate(queues[layer]):
            if len(chosen[layer]) >= limit.get(layer, float('inf')):
                break
            text = safe_read(os.path.join(repo, rel))
            if not text or not text.strip():
                continue
            block = _block(layer, rel, text)
            if spent + len(block) > share:
                set_aside[layer].append((rank, rel, len(block)))
                continue
            chosen[layer].append((rank, rel, block))
            spent += len(block)
        total += spent
    while any(set_aside.values()):
        for layer in BUNDLE_ORDER:
            if len(chosen[layer]) >= limit.get(layer, float('inf')):
                set_aside[layer] = []
            if not set_aside[layer]:
                continue
            rank, rel, size = set_aside[layer].pop(0)
            if total + size > max_chars:
                continue
            text = safe_read(os.path.join(repo, rel))
            if not text or not text.strip():
                continue
            chosen[layer].append((rank, rel, _block(layer, rel, text)))
            total += size
    ordered = [(rel, block) for layer in BUNDLE_ORDER for _rank, rel, block in sorted(chosen[layer])]
    parts = [header] + [block for _rel, block in ordered]
    files = [rel for rel, _block in ordered]  # what left the machine (coderay-3eu)

    if not files:
        # The counts header alone tells the model nothing it can read a backend
        # from, and a truthy bundle hides "found nothing" from the caller.
        return "", {"counts": dict(counts), "included": 0, "files": []}

    return "".join(parts), {"counts": dict(counts), "included": len(files), "files": files}
