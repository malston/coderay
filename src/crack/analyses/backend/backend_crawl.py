"""Crawl a backend into the six layers a request flows through (§10.3).

Every backend is the same six layers with different names:
  route → middleware → handler → service → database → response

We classify each source file into a layer by its path, report a file count per
layer (so the prompts can lead with a concrete number, not an adjective), and
build a bundle that includes the 'spine' files in full — routing, middleware,
and the response/decorator helpers, where teams write their custom idioms — plus
a size-capped sample of the handler/service/model files. Nothing calls an LLM.
"""
import os
from collections import Counter

from crack.core import DEFAULT_SKIP_DIR, list_files, safe_read

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
# Files where teams most often write custom idioms — always included in full.
SPINE_NAMES = ('urls.py', 'rest.py', 'response.py', 'decorator.py', 'decorators.py',
               'middleware.py', 'computed_settings.py', 'routes.rb', 'application_controller.rb')
# Core-action keywords: sample these files first so the trace has the spine endpoint.
CORE_HINTS = ('message', 'send', 'booking', 'book', 'order', 'checkout', 'create',
              'post', 'auth', 'user', 'session', 'event')


def classify(rel):
    """Return the layer a file belongs to, or None.

    The directory conventions below are matched with their surrounding slashes,
    so the path carries a leading one: a repo that keeps `pages/api/` or
    `routes/` at its root reads the same as one that nests them under `src/`."""
    p = '/' + rel.replace(os.sep, '/').lower().lstrip('/')
    base = os.path.basename(p)
    if not p.endswith(SRC_EXT):
        return None
    if any(m in base for m in ('.test.', '.spec.', '_test.', '_spec.', '.stories.')):
        return None
    # Route
    if (base in ('urls.py', 'routes.rb', 'routes.ts', 'router.ts', 'routes.js', 'router.js')
            or base.endswith('_router.ts') or '/pages/api/' in p or '/routes/' in p or '/urls/' in p):
        return 'route'
    # Middleware (incl. decorators and the settings file that lists MIDDLEWARE)
    if ('middleware' in p or base.endswith(('decorator.py', 'decorators.py'))
            or base in ('computed_settings.py',)):
        return 'middleware'
    # Handler
    if '/views/' in p or '/controllers/' in p or '/handlers/' in p or base.endswith(('view.py', 'controller.rb')):
        return 'handler'
    # Service (business logic)
    if '/actions/' in p or '/services/' in p or '/domain/' in p or '/use' in p and 'case' in p:
        return 'service'
    # Database
    if '/models/' in p or base in ('models.py', 'schema.rb') or '/repositories/' in p or '/repository/' in p:
        return 'database'
    # Response
    if 'serializer' in p or '/serializers/' in p or (base.startswith('response') and base.endswith('.py')):
        return 'response'
    return None


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

    # Decide what to include: spine layers in full; handlers/services/models sampled.
    queues = {}
    for layer in ('route', 'middleware', 'response'):
        queues[layer] = sorted(files_by_layer[layer])
    for layer in ('handler', 'service', 'database'):
        ranked = sorted(files_by_layer[layer], key=lambda r: (_priority(r), r))
        queues[layer] = ranked[:per_layer_sample]

    header = "===== LAYER FILE COUNTS (whole repo) =====\n" + "\n".join(
        f"{layer}: {counts[layer]} files" for layer in LAYERS) + "\n"

    # Selection is round-robin across the layers, spine first within a round,
    # so every layer with files reaches the bundle before any layer gets its
    # second file; a file that does not fit is dropped whole, never cut
    # (coderay-q2r.58). Emission is grouped by layer, so the prompts see the
    # same layout whichever order the files were chosen in.
    # ponytail: one sub-limit spine file still spends its whole size from the
    # shared budget; a per-layer share is the upgrade if that starves the rest.
    chosen = {layer: [] for layer in LAYERS}
    total = len(header)
    while any(queues.values()):
        for layer in BUNDLE_ORDER:
            if not queues[layer]:
                continue
            rel = queues[layer].pop(0)
            text = safe_read(os.path.join(repo, rel))
            if not text or not text.strip():
                continue
            block = f"\n===== LAYER {layer.upper()}: {rel} =====\n{text}\n"
            if total + len(block) > max_chars:
                continue
            chosen[layer].append(block)
            total += len(block)
    parts = [header] + [block for layer in BUNDLE_ORDER for block in chosen[layer]]
    kept = len(parts) - 1

    if not kept:
        # The counts header alone tells the model nothing it can read a backend
        # from, and a truthy bundle hides "found nothing" from the caller.
        return "", {"counts": dict(counts), "included": 0}

    return "".join(parts), {"counts": dict(counts), "included": kept}
