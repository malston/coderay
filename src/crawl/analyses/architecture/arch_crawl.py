"""Assemble a compact 'architecture bundle' from a repo's four sources.

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

from crawl.core import DEFAULT_SKIP_DIR, readable

# The shared noise set, keeping docs/ and examples/ because a compose file
# there is exactly the kind of process declaration this crawler is after.
SKIP_DIRS = (DEFAULT_SKIP_DIR - {'docs', 'examples'}) | {'.yarn'}

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
# Go imports name a module path, not a package, so they get their own pattern:
# the well-known clients, plus any module whose path says it is an SDK
# (coderay-5wu.14). A Go import line is `"path"` or `alias "path"`. Written as
# POSIX extended regex, since git grep -E runs it and Python reads it too:
# capturing groups only, bracket classes instead of \w and \s.
GO_SDK_RE = (r"(github\.com/aws/aws-sdk-go(-v2)?|cloud\.google\.com/go/[a-z0-9]+|"
             r"github\.com/(redis/go-redis|go-redis/redis|jackc/pgx|lib/pq|mattn/go-sqlite3|"
             r"stripe/stripe-go|slack-go/slack|sendgrid/sendgrid-go|twilio/twilio-go|"
             r"openai/openai-go|sashabaranov/go-openai|minio/minio-go|elastic/go-elasticsearch|"
             r"segmentio/kafka-go|nats-io/nats\.go|IBM/sarama|Shopify/sarama|rabbitmq/amqp091-go|"
             r"streadway/amqp|getsentry/sentry-go|aws/aws-lambda-go|hashicorp/vault|"
             r"go-sql-driver/mysql|jmoiron/sqlx|uptrace/bun|gorm/gorm)|"
             r"modernc\.org/sqlite|google\.golang\.org/grpc|gorm\.io/gorm|entgo\.io/ent|"
             r"[a-z0-9.-]+/[a-z0-9-]+/([a-z0-9-]+/)*([a-z0-9-]*sdk-go|go-sdk)(/|\"))")
_GO_IMPORT_LINE = r"^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*[[:space:]]+)?\"" + GO_SDK_RE
_GO_VERSION_SEGMENT = re.compile(r"^v\d+$")


def go_sdk_name(path):
    """The client a Go module path names: the repo segment for a host/owner/repo
    path, the service for cloud.google.com/go/<service>, the owner when the repo
    is a generic sdk-go, and the last segment otherwise. A trailing /vN is not
    a name."""
    segments = [s for s in path.split("/") if s and not _GO_VERSION_SEGMENT.match(s)]
    host = segments[0]
    if host == "cloud.google.com" and len(segments) >= 3:
        return segments[2]
    if host == "github.com" and len(segments) >= 3:
        owner, repo = segments[1], segments[2]
        return owner if repo in ("clients", "sdk-go", "go-sdk") or "sdk-go" in segments[3:4] else repo
    return segments[-1]


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield dirpath, dirnames, filenames


def _read(path, limit=200_000, repo=None):
    # A config file in the target repo may be a symlink pointing out of it, and
    # the contents go into a prompt sent to a third-party LLM (coderay-q2r.28).
    # A symlink to an in-repo credential file is refused by its target name.
    # The only credential-named files this crawler reads on purpose are a real
    # `.env*` (variable names only) and `.tfvars` (redacted); every other
    # DEFAULT_SKIP_NAMES entry it walks to, `deploy/credentials.yaml` say, is
    # refused like anywhere else (coderay-q2r.56).
    base = os.path.basename(path).lower()
    wanted_anyway = base.startswith('.env') or base.endswith('.tfvars')
    if repo is not None and not readable(repo, path, credential_names=wanted_anyway):
        return ""
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


def _placeholder(head, value):
    """REDACTED, carrying the closing quote when head swallowed the opening one.

    The head pattern's `"?` eats the quote in `- "DB_PASSWORD=x"`, so the
    value holds the unmatched partner. An odd quote count in head means the
    value's trailing quote is closing it, and dropping it would leave a line
    that no longer parses."""
    for q in ('"', "'"):
        if head.count(q) % 2 and value.endswith(q):
            return REDACTED + q
    return REDACTED


def _nested_is_mapping(lines, i, indent):
    """True if the block under lines[i] is a mapping rather than the key's value.

    `tokens:` followed by `- ghp_...` holds the secret in its items, but a
    compose `secrets:` block holds named entries whose own values are read
    line by line. Only the first deeper line decides which."""
    for line in lines[i + 1:]:
        stripped = line.rstrip('\n\r')
        if not stripped.strip():
            continue
        if _indent(stripped) <= indent:
            return False
        return bool(_ASSIGN_RE.match(stripped) or _BARE_KEY_RE.match(stripped))
    return False

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

# Kubernetes writes a container env var as two sibling lines:
#     - name: API_TOKEN
#       value: sk-live-...
# The sensitive word is on the `name` line, so matching key names line by line
# never sees it and `value` matches nothing (coderay-q2r.30).
_ENV_NAME_RE = re.compile(r'^\s*-?\s*name:\s*["\']?(?P<name>[A-Za-z_][\w.\-]*)["\']?\s*$')
_ENV_VALUE_RE = re.compile(r'^(?P<head>\s*-?\s*value:\s*)(?P<value>\S.*)$')
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
    env_secret = None       # a k8s `name: SECRET_ISH` awaiting its `value:`

    for i, line in enumerate(lines):
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

        # A k8s env entry names the variable on one line and gives its value on
        # the next, so the decision has to carry across the pair.
        env_name = _ENV_NAME_RE.match(stripped)
        if env_name:
            env_secret = indent if SECRET_KEY_RE.search(env_name.group('name')) else None
            out.append(line)
            continue
        env_value = _ENV_VALUE_RE.match(stripped)
        if env_value and env_secret is not None and indent >= env_secret:
            env_secret = None
            out.append(env_value.group('head')
                       + _placeholder(env_value.group('head'), env_value.group('value')) + eol)
            continue
        if env_value or (env_secret is not None and indent <= env_secret):
            env_secret = None

        m = _ASSIGN_RE.match(stripped)
        if m and (under_secret_data or SECRET_KEY_RE.search(m.group('key'))):
            if _BLOCK_SCALAR_RE.match(m.group('value')):
                swallow_indent = indent   # `key: |` -- the secret is below
            out.append(m.group('head') + _placeholder(m.group('head'), m.group('value')) + eol)
            continue

        bare = _BARE_KEY_RE.match(stripped)
        if bare and (under_secret_data or SECRET_KEY_RE.search(bare.group('key'))):
            if not under_secret_data and _nested_is_mapping(lines, i, indent):
                out.append(line)          # compose `secrets:` -- the names are topology
            else:
                swallow_indent = indent   # `tokens:` with the secrets nested below
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

    The redaction seam is coderay's, not the port source's (coderay-q2r.14):
    everything from REDACTED down to _redact, plus the _redact call in
    build_bundle. It is purely additive -- no upstream line is edited except
    that one call -- so a re-port stays mechanical: copy the module, re-add the
    seam, re-point build_bundle.

    ponytail: key-name patterns plus Secret-block tracking, not a secret
    scanner. A credential under an unguessable key name in a file that is not a
    Secret still gets through; reach for detect-secrets or gitleaks if that
    matters. A redacted line keeps its quoting but not its structure: the value
    match runs to end of line, so an inline map or a trailing comment goes with
    it.
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
    """SDK import lines with file:line, via `git grep` (fast). Real proof + paths.

    Returns (lines, unavailable): `unavailable` is None when the grep ran, even
    with no matches, and otherwise says why it could not: `git is not
    installed`, `git could not be run (<error type>)`, `not a git repository`,
    `not a git checkout (inside another repository)`, or `git grep exited N`. The toplevel must be the target
    itself: `git -C` walks up to an enclosing repository, whose index does not
    hold a tarball extracted inside it, and the grep would exit 1. Without that
    second value a tarball export reads as a repo with no SDK imports and the
    report is built on configuration alone (coderay-q2r.15). git's own message
    never travels: it can quote the target repo's .git/config, and the reason
    lands in the HTML footer and the LLM bundle."""
    try:
        top = subprocess.check_output(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                                      text=True, errors="replace", stderr=subprocess.PIPE).strip()
    except FileNotFoundError:
        return "", "git is not installed"
    except OSError as e:
        # A `git` on PATH that cannot be executed, say. The type name travels,
        # not the message, which names paths on the user's machine.
        return "", f"git could not be run ({type(e).__name__})"
    except subprocess.CalledProcessError as e:
        if "not a git repository" in (e.stderr or ""):
            return "", "not a git repository"
        return "", f"git rev-parse exited {e.returncode}"
    if os.path.realpath(top) != os.path.realpath(repo):
        return "", "not a git checkout (inside another repository)"
    try:
        raw = subprocess.check_output(
            ["git", "-C", repo, "grep", "-nE",
             r"(import .*from ['\"]" + SDK_RE + r"|require\(['\"]" + SDK_RE + r"|new (Stripe|Twilio|Redis|S3Client)|"
             + _GO_IMPORT_LINE + ")",
             "--", "*.ts", "*.tsx", "*.js", "*.py", "*.go"],
            text=True, errors="replace", stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:          # git grep: ran, matched nothing
            return "", None
        if "not a git repository" in (e.stderr or ""):
            return "", "not a git repository"
        return "", f"git grep exited {e.returncode}"
    # Emit path:line plus the SDK that matched, never the source line itself.
    # The regex deliberately matches constructors like `new Stripe(...)`, so a
    # hardcoded token in one would otherwise be shipped to the LLM verbatim,
    # and _redact cannot see it -- there is no key=value to key off
    # (coderay-q2r.31). The evidence this section exists to give is "this file
    # talks to this service", which the path and the name carry on their own.
    out, seen = [], set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, lineno, content = parts
        go = re.match(_GO_IMPORT_LINE.replace("[[:space:]]", r"\s"), content)
        if go:
            name = go_sdk_name(re.search(r"\"([^\"]+)\"", content).group(1))
        else:
            m = re.search(SDK_RE, content) or re.search(r'new\s+(Stripe|Twilio|Redis|S3Client)', content)
            name = (m.group(1) if m else "sdk").strip("'\"@")
        entry = f"{path}:{lineno}: {name}"
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
        if len(out) >= max_lines:
            break
    return "\n".join(out), None


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
                env_names.update(_env_names(_read(full, 40_000, repo)))
            elif kind == 'package':
                try:
                    data = json.loads(_read(full, 200_000, repo))
                    for grp in ('dependencies', 'devDependencies'):
                        deps.update(data.get(grp, {}))
                except (ValueError, OSError):
                    pass
            else:
                buckets[kind].append((rel, _redact(_read(full, repo=repo))))

    parts = []
    included = 0        # files whose text actually reached the bundle
    for kind, label in (('compose', 'PROCESS DECLARATION (compose / k8s)'),
                        ('k8s', 'KUBERNETES MANIFESTS'),
                        ('gateway', 'GATEWAY / PLATFORM CONFIG'),
                        ('iac', 'INFRASTRUCTURE-AS-CODE (Terraform)')):
        for rel, text in buckets[kind]:
            if text.strip():
                parts.append(f"===== {label}: {rel} =====\n{text}\n")
                included += 1

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

    sdk, sdk_unavailable = _sdk_grep(repo)
    if sdk:
        parts.append("===== SDK IMPORTS (git grep — file:line: sdk) =====\n" + sdk + "\n")
    elif sdk_unavailable and parts:
        # Only beside real sources: an empty bundle must stay empty so the
        # no-architecture-sources guard still fires. At the top, because the
        # budget cut below takes from the end and the model must read this.
        parts.insert(0, f"===== SDK IMPORTS unavailable: {sdk_unavailable} =====\n"
                        "No import evidence could be gathered, so every connection below is "
                        "configured, not proven live.\n")

    whole = "\n".join(parts)
    bundle = whole[:max_chars]
    if len(whole) > max_chars:
        # The slice lands mid-line, and without this the model reads a config
        # file that simply stops as a complete one (coderay-q2r.27).
        bundle += (f"\n\n===== BUNDLE TRUNCATED at {max_chars:,} of "
                   f"{len(whole):,} chars -- the sources above are incomplete =====\n")
    stats = {
        # What reached the bundle, not what was classified: an empty or
        # unreadable config file is skipped above and must not be counted
        # (coderay-q2r.27).
        "config_files": included,
        "config_files_found": sum(len(v) for v in buckets.values()),
        "truncated": len(whole) > max_chars,
        "env_vars": len(env_names),
        "deps": len(deps),
        "integrations": len(isubs),
        "sdk_lines": sdk.count("\n") + 1 if sdk else 0,
        "sdk_unavailable": sdk_unavailable,
    }
    return bundle, stats
