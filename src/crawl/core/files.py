"""List which files in a repo are worth sending to an LLM.

The defaults aim for "good baseline for most repos": keep common source
extensions, skip the noise (tests, docs, examples, locales, vendored code,
caches, build artifacts).

Override any default by passing your own set. The exposed constants are
frozensets so you can union or difference them:

    from crawl.core import list_files, DEFAULT_SKIP_DIR
    # add to defaults:
    list_files("repo/", skip_dirs=DEFAULT_SKIP_DIR | {"my-generated-dir"})
    # restrict to one language:
    list_files("repo/", keep_ext={".py"})

For path-aware filtering (subpaths, specific file patterns, recursive subdirs)
pass `include` and `exclude` as lists of .gitignore-style patterns:

    # only keep files under src/core/ or pkg/
    list_files("repo/", include=["src/core/**", "pkg/**"])
    # drop everything matching these patterns
    list_files("repo/", exclude=["**/old/**", "**/*_test.go", "examples/legacy/**"])

Patterns are matched against the path relative to `root`. Both lists default
to empty (no path filtering). Patterns follow the same rules as `.gitignore`.
"""
import os
import tempfile

import pathspec


# Source extensions across the common stacks.
DEFAULT_KEEP_EXT = frozenset({
    # web / scripting
    '.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.vue', '.svelte', '.astro',
    '.rb', '.php', '.lua', '.pl',
    '.sh', '.bash', '.zsh', '.fish',
    # systems / compiled
    '.c', '.h', '.cpp', '.hpp', '.cc', '.cxx', '.hh',
    '.go', '.rs', '.zig', '.nim',
    '.java', '.kt', '.kts', '.scala', '.groovy',
    '.cs', '.fs', '.fsx',
    '.swift', '.m', '.mm',
    '.dart',
    # functional / niche
    '.ex', '.exs', '.erl', '.hs', '.clj', '.cljs',
    '.ml', '.mli', '.r', '.jl', '.cr',
    # smart contracts
    '.sol',
    # schema / IDL
    '.sql', '.proto', '.graphql', '.gql', '.thrift',
    # markup / docs / config (often the architecture)
    '.md', '.mdx', '.rst', '.adoc', '.txt',
    '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.conf',
    '.xml', '.html', '.htm',
    # styles
    '.css', '.scss', '.sass', '.less', '.styl',
    # templates
    '.ejs', '.hbs', '.handlebars', '.erb', '.jinja', '.j2', '.liquid',
})

# Committed dotenv templates: variable names with placeholder values. The only
# `.env*` files a crawler reads (coderay-q2r.60).
DOTENV_TEMPLATES = frozenset({'.env.example', '.env.sample'})

# Extensionless filenames that ARE source. Without this set,
# os.path.splitext('Dockerfile')[1] == '' silently drops them.
DEFAULT_KEEP_NAMES = DOTENV_TEMPLATES | frozenset({
    'Dockerfile', 'Containerfile', '.dockerignore',
    'Makefile', 'GNUmakefile', 'Justfile',
    'Rakefile', 'Gemfile', 'Procfile', 'Vagrantfile', 'Brewfile',
    'CMakeLists.txt',
    'README', 'LICENSE', 'NOTICE',
    '.gitignore', '.gitattributes', '.editorconfig',
})

# Directories to skip. Covers the usual noise categories:
# tests, docs, examples, locales, vendored code, build, caches.
DEFAULT_SKIP_DIR = frozenset({
    # vcs
    '.git', '.hg', '.svn',
    # python
    '__pycache__', 'venv', '.venv', 'env', '.tox', '.nox',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache',
    # js / ts
    'node_modules', 'dist', 'build', '.next', '.nuxt', '.svelte-kit',
    '.turbo', '.parcel-cache', '.vercel', '.netlify', '.output',
    # go / rust / java / swift
    'target', 'vendor', '.gradle', 'Pods', 'DerivedData',
    # tests, docs, examples, i18n: the usual noise categories
    'test', 'tests', '__tests__', 'spec',
    'docs', 'examples',
    'locales', 'translations', 'i18n',
    # generated assets
    'assets', 'generated', '__generated__', 'codegen',
    # coverage
    'coverage', 'htmlcov', '.nyc_output',
    # editors (debatable; usually noise)
    '.idea', '.vscode',
    # fixtures and mocks, named the way Go projects name them
    'testdata', 'testutil', 'testutils', 'httptest', 'factorytest',
})

DEFAULT_MAX_FILE_BYTES = 500_000

# Credential-shaped files. Never sent to the LLM or cached, regardless of
# keep_ext/keep_names — these are excluded even if a caller explicitly asks
# for their extension.
DEFAULT_SKIP_NAMES = frozenset({
    '.netrc', '.npmrc', '.pypirc',
    'credentials', 'credentials.json', 'service-account.json', 'client_secret.json',
    'id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa', '.htpasswd', 'terraform.tfvars',
    # coderay-q2r.37: pure-credential names the list missed while it was only
    # crawler noise. Never source, so skipping them costs the crawl nothing.
    'secrets.yml', 'secrets.yaml', 'secrets.json', 'secrets.toml', 'secret.json',
    'credentials.yml', 'credentials.yaml', 'token.json', '.git-credentials', '.pgpass', 'kubeconfig',
})
DEFAULT_SKIP_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.keystore', '.jks', '.ppk',
                         '.tfvars', '.tfstate', '.tfstate.backup')


# Names that mark a file as test scaffolding rather than request-path code:
# the markers every language shares, Rails specs, and Go's test-helper names
# (a name that merely begins with "test", like testimonials.go, is source).
_TEST_MARKERS = ('.test.', '.spec.', '_test.', '.stories.')
_GO_TEST_PREFIXES = ('testhelper', 'testutil', 'testing.', 'testserver', 'testmock', 'test_')


def is_test_file(filename):
    """True if `filename` (a basename) is a test, spec, story or test helper."""
    base = filename.lower()
    return (any(m in base for m in _TEST_MARKERS) or base.endswith('_spec.rb')
            or (base.endswith('.go') and base.startswith(_GO_TEST_PREFIXES)))


def within_repo(repo, path):
    """True if `path` resolves inside `repo`, symlinks followed.

    Every crawler reads files it discovered by walking the target repo, and the
    target repo is untrusted: a checked-in `urls.py` or `docker-compose.yml`
    that is a symlink to /etc/passwd or ~/.aws/credentials is read like any
    other file and its contents go into a prompt sent to a third-party LLM.
    os.walk does not follow directory symlinks, but open() follows file ones.

    Discovery-time containment, the counterpart to the check interfaces already
    applies to LLM-named paths (coderay-q2r.16 / coderay-q2r.28).
    """
    root = os.path.realpath(repo)
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


def readable(repo, path, *, credential_names=False):
    """True if a file a crawler discovered in `repo` may be read into a prompt.

    `within_repo` alone lets `app/urls.py -> ../.env` through: the target is
    inside the repo, it is only credential-named. So the target's own name has
    to clear the credential skip as well, the rule list_files already applies
    at walk time (coderay-q2r.52), and a model-named `.env` is refused the
    same way (coderay-q2r.56).

    `credential_names=True` lets a crawler read a credential-named file it
    walked to itself (the architecture crawler reads a real `.env` for variable
    names); a symlink to one is still refused.
    """
    if not within_repo(repo, path):
        return False
    if credential_names and not os.path.islink(path):
        return True
    return not credential_named(os.path.basename(os.path.realpath(path)))


def credential_named(filename):
    """True if a file's name marks it as credential-bearing: a dotenv file other
    than the committed templates (DOTENV_TEMPLATES), a name on DEFAULT_SKIP_NAMES,
    or a DEFAULT_SKIP_SUFFIXES suffix (keys, certs, Terraform state and vars).
    The one rule every crawler and the git-history redaction apply; a crawler
    that reads a credential-named file on purpose opts in through `readable`."""
    # Case-folded so `credentials.JSON` is refused the same way `credentials.json` is.
    lowered = filename.lower()
    if lowered.startswith('.env'):
        return lowered not in DOTENV_TEMPLATES
    return lowered in DEFAULT_SKIP_NAMES or lowered.endswith(DEFAULT_SKIP_SUFFIXES)


def _wanted(filename, keep_ext, keep_names):
    # keep_names stays exact (Dockerfile, README); the extension check is
    # case-folded like the credential skip.
    if credential_named(filename):
        return False
    if filename in keep_names:
        return True
    return os.path.splitext(filename.lower())[1] in keep_ext


def _compile(patterns):
    """Compile a list of .gitignore-style patterns into a PathSpec, or None if empty."""
    if not patterns:
        return None
    return pathspec.GitIgnoreSpec.from_lines(patterns)


def list_files(root, *, keep_ext=DEFAULT_KEEP_EXT, skip_dirs=DEFAULT_SKIP_DIR,
               keep_names=DEFAULT_KEEP_NAMES, max_file_bytes=DEFAULT_MAX_FILE_BYTES,
               include=None, exclude=None):
    """Walk the tree and return paths that pass the filters. No file content read.

    Args:
        root: directory to walk.
        keep_ext: file extensions to keep (DEFAULT_KEEP_EXT covers ~85 languages).
        skip_dirs: directory basenames to prune entirely (DEFAULT_SKIP_DIR covers
            the universal noise: tests, docs, build artifacts, caches, vendored).
        keep_names: extensionless filenames that ARE source (Dockerfile, Makefile).
        max_file_bytes: per-file size cap. Drops generated files and oversized dumps.
        include: list of .gitignore-style patterns. If non-empty, ONLY files whose
            relative path matches at least one pattern are kept. Examples:
                ["src/core/**", "pkg/**"]  # restrict to two subtrees
                ["**/*.go", "go.mod"]      # only Go source + module file
        exclude: list of .gitignore-style patterns. Files whose relative path
            matches any pattern are dropped. Applied after `include`. Examples:
                ["**/*_test.go", "examples/legacy/**"]
                ["docs/old/**", "**/.generated.*"]
    """
    out = []
    skip = set(skip_dirs)
    keep_ext = {e.lower() for e in keep_ext}
    include_spec = _compile(include)
    exclude_spec = _compile(exclude)
    real_root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # Sorted so a budgeted caller includes the same files on every
        # filesystem; os.walk otherwise yields subtrees in scandir order.
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for f in sorted(filenames):
            if not _wanted(f, keep_ext, keep_names):
                continue
            path = os.path.join(dirpath, f)
            real = os.path.realpath(path)
            if not real.startswith(real_root + os.sep):
                continue  # symlink resolving outside the repo root
            # coderay-q2r.52: a symlink can rename a skipped file into a
            # source-looking one (src/config.py -> ../.env), so the target's
            # own name has to pass the filter too.
            if os.path.islink(path) and not _wanted(os.path.basename(real), keep_ext, keep_names):
                continue
            rel = os.path.relpath(path, root)
            if include_spec is not None and not include_spec.match_file(rel):
                continue
            if exclude_spec is not None and exclude_spec.match_file(rel):
                continue
            if max_file_bytes:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size > max_file_bytes:
                    continue
            out.append(path)
    return out


def safe_read(path, max_chars=None):
    """Read a file, skip per-file decode and OS errors (permission denied,
    broken symlink, vanished file).

    The only legitimate try/except in this module: one bad file should not
    kill a walk over 10,000 files.

    max_chars, if given, reads only that many characters instead of the whole
    file -- use this when the caller only needs a preview.
    """
    try:
        with open(path, encoding='utf-8') as f:
            return f.read(max_chars) if max_chars is not None else f.read()
    except (UnicodeDecodeError, OSError):
        return None


def write_text_atomic(path, text):
    """Write `text` to `path` whole or not at all: into a temporary file beside
    it, then one rename over the target. A crash or a Ctrl-C part way leaves
    the old file (or none), never a truncated one passing for a record
    (coderay-5wu.23). Returns `path`."""
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path
