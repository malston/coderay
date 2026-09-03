"""Assemble a compact 'architecture bundle' from a repo's four sources (§9.2).

An architecture never lives in one file; you overlay four sources:
  compose / Procfile / k8s   the services the team RUNS
  .env (names only)          the external services it's configured to CALL
  IaC (*.tf)                 the managed cloud resources underneath
  application code           the imports that PROVE a call is live

Feeding a 600k-line repo whole is impossible, so we build a bundle small enough
for one LLM pass but dense enough to inventory the architecture: the config
files in full, env var NAMES (never values), the union of package.json
dependencies (which name every SDK), the integration directories, and the SDK
`import` lines found by `git grep` (real file paths, proof a connection is live).
Nothing here calls an LLM.
"""
import json
import os
import re
import subprocess

SKIP_DIRS = frozenset({
    '.git', '.hg', '.svn', 'node_modules', 'dist', 'build', '.next', '.nuxt',
    'target', 'vendor', 'venv', '.venv', '__pycache__', '.cache', 'coverage',
    '.turbo', '.yarn', 'test', 'tests', '__tests__',
})

GATEWAY_NAMES = frozenset({
    'kong.yml', 'kong.yaml', 'nginx.conf', 'vercel.json', 'netlify.toml',
    'next.config.js', 'next.config.mjs', 'next.config.ts', 'fly.toml',
    'render.yaml', 'railway.json', 'Procfile',
})

# SDK / client imports that name an external node. Kept broad but specific.
SDK_RE = (r"(stripe|twilio|@?aws-sdk|aws-sdk|googleapis|@google-cloud|ioredis|"
          r"'redis'|\"redis\"|nodemailer|@sendgrid|resend|@slack|slack|openai|"
          r"@sentry|@prisma/client|mongodb|mysql2?|pg|kafkajs|bullmq|amqplib|"
          r"@aws-sdk/client-s3|boto3|sib-api|mailgun|postmark|hubspot|"
          r"@salesforce|algolia|elastic|pusher|ably|firebase)")


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield dirpath, dirnames, filenames


def _read(path, limit=200_000):
    try:
        return open(path, encoding='utf-8', errors='replace').read()[:limit]
    except OSError:
        return ""


def _env_names(text):
    """Var NAMES only — never the secret values."""
    names = []
    for line in text.splitlines():
        m = re.match(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=', line)
        if m:
            names.append(m.group(1))
    return names


REDACTED = '[REDACTED]'

# Key names whose value is a credential often enough that guessing wrong costs
# nothing: the analysis needs to know STRIPE_KEY exists, never what it equals.
SECRET_KEY_RE = re.compile(
    r'(pass|pwd|secret|token|key|cred|auth|private|salt|signature|dsn|'
    r'session|cookie|licen[cs]e|webhook)', re.I)

# key: value / key = value / key=value, keeping the indent and the separator so
# the redacted line still reads as the format it came from. The key length is
# bounded to keep the pattern's cost linear on a long line.
_ASSIGN_RE = re.compile(r'^(?P<head>\s*-?\s*"?(?P<key>[A-Za-z_][\w.\-]{0,127})"?\s*[:=]\s*)'
                        r'(?P<value>\S.*)$')

# `key:` with nothing after it, which introduces a nested block or sequence.
_BARE_KEY_RE = re.compile(r'^(?P<head>\s*-?\s*"?(?P<key>[A-Za-z_][\w.\-]{0,127})"?\s*:)\s*$')

# A YAML block or folded scalar: the value is on the following, deeper lines.
_BLOCK_SCALAR_RE = re.compile(r'^[|>][+-]?\d*\s*(#.*)?$')

# A credential embedded in a connection string, which no key name reveals. The
# user segment allows zero characters: redis://:password@host is the standard
# passwordless-username form. Every run is length-bounded -- unbounded, this sub
# scans from each of a long line's positions looking for '://', which is
# quadratic and took a minute on a 200k-char file.
_URL_CRED_RE = re.compile(r'(?P<scheme>[a-zA-Z][\w+.\-]{0,31}://[^\s:/@]{0,255}:)'
                          r'(?P<pw>[^\s@/]{1,255})(?=@)')

# A Secret's keys are arbitrary, so nothing about the key name marks the value.
# The document is scanned for `kind: Secret` before any line is redacted,
# because YAML does not order mapping keys and a serializer that sorts them
# emits data: before kind:.
_SECRET_KIND_RE = re.compile(r'^\s*kind:\s*["\']?Secret\b', re.I)
_SECRET_DATA_RE = re.compile(r'^\s*(data|stringData):\s*$')
_DOC_BREAK_RE = re.compile(r'^(---|\.\.\.)\s*$')


def _indent(line):
    return len(line) - len(line.lstrip())


def _documents(lines):
    """Split on YAML document breaks, yielding each break as its own chunk."""
    current = []
    for line in lines:
        if _DOC_BREAK_RE.match(line.rstrip('\n\r')):
            if current:
                yield current
            yield [line]
            current = []
        else:
            current.append(line)
    if current:
        yield current


def _redact_document(lines):
    # Whole-document scan first: `kind: Secret` may appear after `data:`.
    in_secret_doc = any(_SECRET_KIND_RE.match(l.rstrip('\n\r')) for l in lines)
    out = []
    data_indent = None      # indent of a Secret's `data:` key while inside it
    swallow_indent = None   # indent of a redacted key whose value runs on below

    for line in lines:
        stripped = line.rstrip('\n\r')
        eol = line[len(stripped):]
        if not stripped.strip():
            out.append(line)
            continue
        indent = _indent(stripped)

        # Lines deeper than a key we already redacted ARE that key's value.
        if swallow_indent is not None:
            if indent > swallow_indent:
                continue
            swallow_indent = None

        # Leaving the Secret's data: block, so stop redacting everything.
        if data_indent is not None and indent <= data_indent:
            data_indent = None

        if in_secret_doc and data_indent is None and _SECRET_DATA_RE.match(stripped):
            data_indent = indent
            out.append(line)
            continue

        under_secret_data = data_indent is not None

        m = _ASSIGN_RE.match(stripped)
        if m and (under_secret_data or SECRET_KEY_RE.search(m.group('key'))):
            if _BLOCK_SCALAR_RE.match(m.group('value')):
                swallow_indent = indent   # `key: |` -- the secret is below
            out.append(m.group('head') + REDACTED + eol)
            continue

        bare = _BARE_KEY_RE.match(stripped)
        if bare and (under_secret_data or SECRET_KEY_RE.search(bare.group('key'))):
            swallow_indent = indent       # `tokens:` with the secrets nested below
            out.append(bare.group('head') + ' ' + REDACTED + eol)
            continue

        out.append(_URL_CRED_RE.sub(lambda x: x.group('scheme') + REDACTED, line))
    return out


def _redact(text):
    """Strip credential values out of a config file, keeping its shape.

    The bundle is sent to a third-party LLM API, so a password in a compose
    `environment:` block or a committed `.tfvars` would leave the machine. What
    the analysis needs from these files is the topology -- services, images,
    ports, resources, and the NAMES of the things they are wired to -- never a
    value. Names, structure and indentation survive; values under a key that
    reads like a credential, and every value in a Kubernetes Secret, do not.

    This function and its call in build_bundle are coderay's, not the port
    source's (coderay-q2r.14). Everything else in this module is a verbatim
    copy; keep the diff to this one seam so a re-port stays mechanical.

    ponytail: key-name patterns plus Secret-block tracking, not a secret
    scanner. A credential under an unguessable key name in a file that is not a
    Secret still gets through; reach for detect-secrets or gitleaks if that
    matters. A redacted line is not guaranteed to re-parse -- the value match
    runs to end of line, so a trailing quote or inline map goes with it.
    """
    out = []
    for doc in _documents(text.splitlines(keepends=True)):
        out.extend(_redact_document(doc))
    return "".join(out)


def _classify(rel):
    # The manifest directories below are matched with their surrounding
    # slashes, so the path carries a leading one: `k8s/` and `deploy/` sit at
    # the repo root as often as they sit under `infra/`.
    p = '/' + rel.replace(os.sep, '/').lstrip('/')
    base = os.path.basename(p).lower()
    if base.startswith('docker-compose') or base in ('compose.yaml', 'compose.yml'):
        return 'compose'
    if os.path.basename(p) == 'Procfile':
        return 'gateway'
    if base.startswith('.env'):
        return 'env'
    if base.endswith('.tf') or base.endswith('.tfvars'):
        return 'iac'
    if os.path.basename(p) in GATEWAY_NAMES:
        return 'gateway'
    if base == 'package.json':
        return 'package'
    if base.endswith(('.yaml', '.yml')) and any(
            seg in p for seg in ('/k8s/', '/kubernetes/', '/manifests/', '/deploy/', '/charts/', '/helm/')):
        return 'k8s'
    return None


def _sdk_grep(repo, max_lines=400):
    """SDK import lines with file:line, via `git grep` (fast). Real proof + paths."""
    try:
        raw = subprocess.check_output(
            ["git", "-C", repo, "grep", "-nE",
             r"(import .*from ['\"]" + SDK_RE + r"|require\(['\"]" + SDK_RE + r"|new (Stripe|Twilio|Redis|S3Client))",
             "--", "*.ts", "*.tsx", "*.js", "*.py", "*.go"],
            text=True, errors="replace", stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ""
    lines = [l for l in raw.splitlines() if l.strip()]
    return "\n".join(lines[:max_lines])


def _integration_dirs(repo):
    """The long tail of integrations — one dir per external service."""
    for cand in ("packages/app-store", "app-store", "packages/integrations", "integrations"):
        full = os.path.join(repo, cand)
        if os.path.isdir(full):
            subs = sorted(d for d in os.listdir(full)
                          if os.path.isdir(os.path.join(full, d)) and not d.startswith(('_', '.')))
            if subs:
                return cand, subs
    return None, []


def build_bundle(repo, max_chars=500_000):
    """Return (bundle_text, stats)."""
    buckets = {k: [] for k in ('compose', 'k8s', 'gateway', 'iac')}
    env_names, deps = set(), {}
    for dirpath, _dn, filenames in _walk(repo):
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), repo)
            kind = _classify(rel)
            if kind is None:
                continue
            full = os.path.join(dirpath, f)
            if kind == 'env':
                env_names.update(_env_names(_read(full, 40_000)))
            elif kind == 'package':
                try:
                    data = json.loads(_read(full, 200_000))
                    for grp in ('dependencies', 'devDependencies'):
                        deps.update(data.get(grp, {}))
                except (ValueError, OSError):
                    pass
            else:
                buckets[kind].append((rel, _redact(_read(full))))

    parts = []
    for kind, label in (('compose', 'PROCESS DECLARATION (compose / k8s)'),
                        ('k8s', 'KUBERNETES MANIFESTS'),
                        ('gateway', 'GATEWAY / PLATFORM CONFIG'),
                        ('iac', 'INFRASTRUCTURE-AS-CODE (Terraform)')):
        for rel, text in buckets[kind]:
            if text.strip():
                parts.append(f"===== {label}: {rel} =====\n{text}\n")

    if env_names:
        parts.append("===== ENVIRONMENT VARIABLE NAMES (values omitted) =====\n"
                     + "\n".join(sorted(env_names)) + "\n")
    if deps:
        parts.append("===== PACKAGE DEPENDENCIES (name @ version) =====\n"
                     + "\n".join(f"{k} @ {v}" for k, v in sorted(deps.items())) + "\n")

    idir, isubs = _integration_dirs(repo)
    if isubs:
        parts.append(f"===== INTEGRATION DIRECTORIES ({idir}, {len(isubs)} total) =====\n"
                     + ", ".join(isubs) + "\n")

    sdk = _sdk_grep(repo)
    if sdk:
        parts.append("===== SDK IMPORT LINES (git grep — file:line: import) =====\n" + sdk + "\n")

    bundle = "\n".join(parts)[:max_chars]
    stats = {
        "config_files": sum(len(v) for v in buckets.values()),
        "env_vars": len(env_names),
        "deps": len(deps),
        "integrations": len(isubs),
        "sdk_lines": sdk.count("\n") + 1 if sdk else 0,
    }
    return bundle, stats
