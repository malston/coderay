import os
import json

import pytest

from crawl.analyses.architecture import arch_crawl as ac


@pytest.mark.parametrize("rel,kind", [
    ("docker-compose.yml", "compose"),
    ("docker-compose.prod.yaml", "compose"),
    ("compose.yaml", "compose"),
    ("Procfile", "gateway"),
    ("apps/web/next.config.js", "gateway"),
    ("vercel.json", "gateway"),
    ("ops/nginx.conf", "gateway"),
    (".env", "env"),
    (".env.example", "env"),
    ("infra/main.tf", "iac"),
    ("infra/prod.tfvars", "iac"),
    ("package.json", "package"),
    ("deploy/k8s/api.yaml", "k8s"),
    ("ops/manifests/web.yml", "k8s"),
])
def test_classify_maps_a_path_to_its_source_kind(rel, kind):
    assert ac._classify(rel) == kind


@pytest.mark.parametrize("rel", [
    "README.md", "src/index.ts", "docs/architecture.png", "config.yaml",
])
def test_classify_returns_none_for_a_file_that_is_not_an_architecture_source(rel):
    assert ac._classify(rel) is None


@pytest.mark.parametrize("rel", [
    "infra/lib/api-stack.ts",     # AWS CDK
    "infrastructure/index.ts",    # Pulumi
    "template.yaml",              # AWS SAM
    "Pulumi.yaml",                # Pulumi project file
])
def test_classify_is_blind_to_infrastructure_written_in_a_general_purpose_language(rel):
    """Known limitation, tracked as coderay-q2r.10.

    _classify keys off extension or exact filename, so CDK and Pulumi stacks
    (ordinary .ts/.py programs) and SAM/Pulumi templates (ordinary .yaml outside
    a k8s directory) match nothing. A CDK repo reports `0 config files` while
    its stacks sit in infra/lib/. Inherited from the port source and
    deliberately not fixed here: _classify is part of the verbatim copy (only
    _redact and its call site are coderay's). When
    upstream fixes it this test fails, which is the signal to re-port and
    invert it.
    """
    assert ac._classify(rel) is None


@pytest.mark.parametrize("rel", ["k8s/api.yaml", "manifests/web.yml", "charts/api/values.yaml"])
def test_classify_reads_a_manifest_directory_at_the_repo_root(rel):
    """Fixed upstream in 4a74f7e and re-ported at pin 34f0ad2, alongside the
    same fix to backend's crawl (coderay-q2r.7) and to interfaces.

    Never had a bead of its own -- coderay-q2r.10 covers only the CDK, Pulumi
    and SAM classifier gap, and is still open for it.

    The k8s rules match their surrounding slashes ('/k8s/', '/charts/'), and
    os.path.relpath never produces a leading one, so a manifest directory at
    the repository root used to be skipped while the identical directory one
    level down classified. Both forms must classify now, which is what
    separates the fix from one that merely stripped the slashes.
    """
    assert ac._classify(rel) == "k8s"
    assert ac._classify("deploy/" + rel) == "k8s"


def test_env_names_keeps_the_names_and_never_the_values():
    """The bundle goes to an LLM, so a leaked value is a leaked secret."""
    names = ac._env_names(
        "export STRIPE_SECRET_KEY=sk_live_51H_realsecret\n"
        "DATABASE_URL=postgres://user:hunter2@db/app\n"
        "lowercase_ignored=1\n"
        "# COMMENTED_OUT=x\n"
    )
    assert names == ["STRIPE_SECRET_KEY", "DATABASE_URL"]


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


@pytest.mark.parametrize("line,secret", [
    ("      STRIPE_KEY: sk_live_51HxxREALSECRET", "sk_live_51HxxREALSECRET"),
    ("      - DB_PASSWORD=hunter2", "hunter2"),
    ('db_password = "hunter2"', "hunter2"),
    ('API_TOKEN = "tok_abc123"', "tok_abc123"),
    ("  aws_secret_access_key: wJalrXUtnFEMI", "wJalrXUtnFEMI"),
    ("  private_key: MIIEvQIBADANBg", "MIIEvQIBADANBg"),
    ("  DATABASE_URL: postgres://app:hunter2@db:5432/app", "hunter2"),
])
def test_redact_removes_a_secret_value(line, secret):
    out = ac._redact(line)
    assert secret not in out
    assert ac.REDACTED in out


@pytest.mark.parametrize("label,text,secret", [
    # The value is on the lines BELOW the key, so a same-line match writes
    # [REDACTED] over the `|` indicator and leaves the secret sitting under it.
    ("yaml block scalar", 'api_key: |\n  sk-live-DEADBEEFSECRET\n', "sk-live-DEADBEEFSECRET"),
    ("yaml folded scalar", 'password: >\n  hunter2SECRET\n', "hunter2SECRET"),
    ("sequence under a secret key", 'tokens:\n  - ghp_aaaaSECRET\n', "ghp_aaaaSECRET"),
    ("value wrapped to the next line", '{\n  "apiKey":\n    "sk-live-SECRET"\n}\n', "sk-live-SECRET"),
    # kubectl emits keys alphabetically, so data: arrives before kind: and a
    # tracker armed only after seeing kind: never fires.
    ("kubectl-ordered Secret",
     'apiVersion: v1\ndata:\n  blorp: aGVsbG9SECRET\nkind: Secret\n', "aGVsbG9SECRET"),
    ("block scalar inside a Secret",
     'kind: Secret\nstringData:\n  tls.key: |\n    MIIEowSECRETKEY\n', "MIIEowSECRETKEY"),
    # redis://:password@host is the standard passwordless-username form, and
    # neither REDIS_URL nor AMQP matches any secret-word pattern.
    ("connection string with no username",
     'REDIS_URL: redis://:hunter2SECRET@localhost:6379/0\n', "hunter2SECRET"),
])
def test_redact_reaches_a_secret_the_key_name_alone_would_miss(label, text, secret):
    """Every case here leaked past the first version of _redact.

    Each one sits under a key SECRET_KEY_RE already covers, or inside a
    Kubernetes Secret, so these are failures of the mechanism _redact claims to
    have rather than the documented ceiling. Found reviewing coderay-q2r.14.
    """
    assert secret not in ac._redact(text), label


def test_redact_stops_at_the_end_of_a_secret_data_block():
    """The Secret's own metadata is topology the analysis exists to report.

    Redacting to end of document would take the name and namespace with it, so
    the model could no longer say which secret it is or where it lives.
    """
    out = ac._redact("kind: Secret\ndata:\n  blorp: aGVsbG9SECRET\n"
                     "metadata:\n  name: my-app\n  namespace: prod\n")
    assert "aGVsbG9SECRET" not in out
    assert "name: my-app" in out
    assert "namespace: prod" in out


@pytest.mark.parametrize("line", [
    "    image: envoyproxy/envoy:v1.29",
    "      - '5432:5432'",
    "  replicas: 3",
    '  instance_type = "t3.medium"',
    "      LOG_LEVEL: debug",
    "    depends_on:",
])
def test_redact_keeps_the_topology_the_analysis_is_for(line):
    """Redaction that ate image names or ports would break the analysis."""
    assert ac._redact(line) == line


def test_redact_covers_every_value_under_a_kubernetes_secret():
    """A Secret's keys are arbitrary, so no key-name pattern can catch them.

    `pw` below matches no secret-word pattern; only knowing it sits under a
    Secret's data: block catches it. That is what separates block tracking
    from a per-line key match.
    """
    manifest = ("kind: Secret\n"
                "metadata:\n"
                "  name: api-creds\n"
                "data:\n"
                "  pw: aHVudGVyMg==\n"
                "  tls.crt: TUlJRXZR\n")
    out = ac._redact(manifest)
    assert "aHVudGVyMg==" not in out
    assert "TUlJRXZR" not in out
    # The shape of the manifest survives, so the LLM still sees a Secret exists.
    assert "kind: Secret" in out
    assert "name: api-creds" in out
    assert "pw:" in out


def test_redact_stops_at_the_end_of_the_secret_block():
    """A ConfigMap following a Secret must not be redacted along with it."""
    manifest = ("kind: Secret\n"
                "data:\n"
                "  pw: aHVudGVyMg==\n"
                "---\n"
                "kind: ConfigMap\n"
                "data:\n"
                "  LOG_LEVEL: debug\n")
    out = ac._redact(manifest)
    assert "aHVudGVyMg==" not in out
    assert "LOG_LEVEL: debug" in out


def test_redact_leaves_a_line_it_rewrote_still_parseable():
    """The head pattern eats the opening quote, so [REDACTED] must carry the
    closing one or the line comes out unbalanced."""
    assert ac._redact('  - "DB_PASSWORD=hunter2"\n') == '  - "DB_PASSWORD=[REDACTED]"\n'
    # A value that already carries both of its own quotes needs no help.
    assert ac._redact('AWS_SECRET_ACCESS_KEY: "abc123"\n') == 'AWS_SECRET_ACCESS_KEY: [REDACTED]\n'


def test_redact_keeps_a_named_block_under_a_secret_sounding_key():
    """compose declares its secrets by NAME under a top-level `secrets:` key.

    Swallowing everything nested under a key matching SECRET_KEY_RE takes that
    whole block with it -- names, files and all -- which is the topology the
    analysis exists to read. A nested mapping is structure; only a sequence or
    a scalar under the key is the value.
    """
    compose = ("secrets:\n"
               "  db_password:\n"
               "    file: ./secrets/db.txt\n")
    assert ac._redact(compose) == compose


def test_redact_still_reaches_a_secret_nested_under_a_kept_block():
    """Keeping the block does not mean trusting its leaves."""
    out = ac._redact("auth:\n  api_token: hunter2SECRET\n  host: db.internal\n")
    assert "hunter2SECRET" not in out
    assert "host: db.internal" in out


def test_redact_is_linear_on_a_long_line_with_no_separator():
    """_URL_CRED_RE's runs must stay bounded.

    It is an unanchored sub, so it retries from every position on the line;
    unbounded, each attempt consumes the rest of the line looking for "://"
    before failing, which is quadratic. A 200k-char minified config took 64
    seconds. (_ASSIGN_RE is anchored and stays linear either way -- measured --
    so its bound is cheap insurance, not what this test protects.) The margin
    here is ~100x, so it fails on a genuine regression and not a slow machine.
    """
    import time
    line = "s" * 200_000
    start = time.perf_counter()
    ac._redact(line)
    assert time.perf_counter() - start < 1.0


def test_no_source_sends_a_secret_value_to_the_bundle(tmp_path):
    """coderay-q2r.14. The bundle goes to a third-party LLM API.

    Every file kind the crawl collects is checked here, because the defect
    this replaced was exactly that the rule reached only one of them.
    """
    repo = _repo(tmp_path, {
        ".env": "DOTENV_SECRET=leaked-from-dotenv\n",
        "infra/prod.tfvars": 'db_password = "leaked-from-tfvars"\n',
        "docker-compose.yml": "services:\n  api:\n    image: api:1.2\n"
                              "    environment:\n"
                              "      STRIPE_KEY: leaked-from-compose\n",
        "deploy/k8s/secret.yaml": "kind: Secret\ndata:\n  pw: leaked-from-k8s\n",
        "fly.toml": '[env]\nAPI_TOKEN = "leaked-from-fly"\n',
    })
    bundle, _stats = ac.build_bundle(repo)

    for leaked in ("leaked-from-dotenv", "leaked-from-tfvars", "leaked-from-compose",
                   "leaked-from-k8s", "leaked-from-fly"):
        assert leaked not in bundle, f"{leaked} reached the bundle"

    # The names and the topology still reach the model.
    assert "DOTENV_SECRET" in bundle
    assert "STRIPE_KEY" in bundle
    assert "image: api:1.2" in bundle


def test_sdk_imports_say_so_when_the_target_is_not_a_git_checkout(tmp_path):
    """coderay-q2r.15. Without a distinct signal, `git grep` exiting 128 (not
    a repository) reads the same as exit 1 (no matches), a tarball export
    loses the one evidence class that proves a connection is live, and the
    report reads as if the repo had no SDK imports.

    The repo below holds a real SDK import a working `git grep` would find;
    tmp_path is not a git checkout. The count stays zero, and the stats and the
    bundle both say why."""
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "src/pay.ts": "import Stripe from 'stripe';\n",
    })
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_lines"] == 0
    assert "not a git repository" in stats["sdk_unavailable"]
    assert "SDK IMPORTS unavailable" in bundle and "not a git repository" in bundle
    assert "configured, not proven live" in bundle


def _git_grep_fails(monkeypatch, repo, returncode, stderr):
    """rev-parse answers with the target itself; the grep fails as given."""
    import subprocess
    def run(cmd, **kw):
        if "rev-parse" in cmd:
            return repo + "\n"
        raise subprocess.CalledProcessError(returncode, cmd, output="", stderr=stderr)
    monkeypatch.setattr(ac.subprocess, "check_output", run)


def test_sdk_unavailable_reason_never_carries_git_stderr_text(tmp_path, monkeypatch):
    """git's fatal messages quote the target repo's own .git/config, and the
    reason reaches the HTML footer and the LLM bundle. Only a known phrase or
    the exit code may travel; the raw text stays out of both."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n"})
    _git_grep_fails(monkeypatch, repo, 128, "fatal: bad boolean config value '<script>alert(1)</script>' for 'grep.linenumber'\n")
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_unavailable"] == "git grep exited 128"
    assert "<script>" not in bundle and "alert" not in bundle


def test_sdk_unavailable_reason_finds_the_phrase_behind_a_warning_line(tmp_path, monkeypatch):
    """git can print warning: lines before fatal:; the phrase is searched in the whole output."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n"})
    _git_grep_fails(monkeypatch, repo, 128, "warning: something\nfatal: not a git repository: '/x'\n")
    _, stats = ac.build_bundle(repo)
    assert stats["sdk_unavailable"] == "not a git repository"


def test_sdk_unavailable_section_survives_bundle_truncation(tmp_path):
    """The note the model must read sits at the top of the bundle, since the
    budget cut takes from the end."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services:\n" + "  a: b\n" * 2000})
    bundle, stats = ac.build_bundle(repo, max_chars=2_000)
    assert stats["truncated"] and stats["sdk_unavailable"]
    assert "SDK IMPORTS unavailable" in bundle


def test_sdk_imports_say_so_when_the_target_sits_inside_another_checkout(tmp_path):
    """`git -C` walks up to the enclosing repository, and `git grep` searches
    tracked files only, so a tarball extracted inside some other checkout
    exits 1 and reads as a real zero. The toplevel must be the target itself."""
    import subprocess
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    repo = _repo(tmp_path / "vendor" / "export", {
        "docker-compose.yml": "services: {}\n",
        "src/pay.ts": "import Stripe from 'stripe';\n",
    })
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_lines"] == 0
    assert stats["sdk_unavailable"] == "not a git checkout (inside another repository)"
    assert "SDK IMPORTS unavailable" in bundle


def test_sdk_imports_say_so_when_git_is_not_installed(tmp_path, monkeypatch):
    """A missing git binary raises FileNotFoundError before git can exit at
    all; it must be reported as unavailable, not as zero imports. PATH holds
    one empty directory, so the exec lookup fails for real."""
    (tmp_path / "emptybin").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "emptybin"))
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n"})
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_lines"] == 0
    assert "git is not installed" in stats["sdk_unavailable"]
    assert "SDK IMPORTS unavailable" in bundle


def test_sdk_imports_say_so_when_git_cannot_be_run(tmp_path, monkeypatch):
    """A `git` on PATH that is not executable raises PermissionError, an OSError
    that is not FileNotFoundError; it must be reported, not crash the run."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "git").write_text("not a program\n"); (bindir / "git").chmod(0o644)
    monkeypatch.setenv("PATH", str(bindir))
    repo = _repo(tmp_path / "repo", {"docker-compose.yml": "services: {}\n"})
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_unavailable"] == "git could not be run (PermissionError)"
    assert "SDK IMPORTS unavailable" in bundle


def test_sdk_grep_with_no_matches_is_not_reported_as_unavailable(tmp_path):
    """Exit 1 from `git grep` means it ran and found nothing; that is a real
    zero and must not carry the unavailable note."""
    import subprocess
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n", "a.ts": "const x = 1;\n"})
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", repo] + cmd, check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "x"], check=True)
    bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_lines"] == 0 and stats["sdk_unavailable"] is None
    assert "SDK IMPORTS unavailable" not in bundle


def test_build_bundle_overlays_the_four_sources_and_counts_them(tmp_path):
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services:\n  api:\n    image: api\n",
        "deploy/k8s/api.yaml": "kind: Deployment\n",
        "Procfile": "web: node server.js\n",
        "infra/main.tf": 'resource "aws_s3_bucket" "uploads" {}\n',
        ".env.example": "STRIPE_SECRET_KEY=sk_test_x\nREDIS_URL=redis://localhost\n",
        "package.json": json.dumps({"dependencies": {"stripe": "^14"},
                                    "devDependencies": {"vitest": "^1"}}),
    })
    bundle, stats = ac.build_bundle(repo)

    assert stats == {"config_files": 4, "config_files_found": 4, "truncated": False,
                     "env_vars": 2, "deps": 2, "integrations": 0, "sdk_lines": 0,
                     "sdk_unavailable": "not a git repository"}
    assert "PROCESS DECLARATION (compose / k8s): docker-compose.yml" in bundle
    assert "KUBERNETES MANIFESTS: deploy/k8s/api.yaml" in bundle
    assert "GATEWAY / PLATFORM CONFIG: Procfile" in bundle
    assert "INFRASTRUCTURE-AS-CODE (Terraform): infra/main.tf" in bundle
    assert "aws_s3_bucket" in bundle
    # Env vars reach the bundle as names only.
    assert "STRIPE_SECRET_KEY" in bundle and "sk_test_x" not in bundle
    assert "stripe @ ^14" in bundle and "vitest @ ^1" in bundle


def test_build_bundle_returns_nothing_for_a_repo_with_no_architecture_sources(tmp_path):
    """Unlike backend's bundle, this one has no header prepended, so it really
    is empty and BuildBundle's `assert bundle.strip()` guard can fire."""
    repo = _repo(tmp_path, {"README.md": "# a single-binary tool\n",
                            "src/main.go": "package main\n"})
    bundle, stats = ac.build_bundle(repo)
    assert bundle == ""
    assert stats["config_files"] == 0
    # The unavailable note is set but not written: the bundle stays empty so
    # the guard fires (coderay-q2r.15).
    assert stats["sdk_unavailable"] == "not a git repository"


def test_build_bundle_skips_ignored_directories(tmp_path):
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "node_modules/pkg/docker-compose.yml": "ignored-compose\n",
        "tests/docker-compose.yml": "ignored-compose\n",
        "vendor/infra/main.tf": "ignored-tf\n",
    })
    bundle, stats = ac.build_bundle(repo)
    assert stats["config_files"] == 1
    assert "ignored" not in bundle


def test_build_bundle_unions_dependencies_from_every_package_json(tmp_path):
    repo = _repo(tmp_path, {
        "package.json": json.dumps({"dependencies": {"stripe": "^14"}}),
        "apps/web/package.json": json.dumps({"dependencies": {"next": "^15"}}),
    })
    _bundle, stats = ac.build_bundle(repo)
    assert stats["deps"] == 2


def test_build_bundle_tolerates_a_malformed_package_json(tmp_path):
    repo = _repo(tmp_path, {
        "package.json": "{not json",
        "apps/web/package.json": json.dumps({"dependencies": {"next": "^15"}}),
    })
    _bundle, stats = ac.build_bundle(repo)
    assert stats["deps"] == 1


def test_build_bundle_lists_the_integration_directories(tmp_path):
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "packages/app-store/stripe/index.ts": "x\n",
        "packages/app-store/zoom/index.ts": "x\n",
        "packages/app-store/_utils/helper.ts": "x\n",
    })
    bundle, stats = ac.build_bundle(repo)
    assert stats["integrations"] == 2
    assert "INTEGRATION DIRECTORIES (packages/app-store, 2 total)" in bundle
    assert "stripe, zoom" in bundle
    # Leading-underscore directories are scaffolding, not integrations.
    assert "_utils" not in bundle


def test_build_bundle_caps_the_total_size_and_says_it_truncated(tmp_path):
    """A slice lands mid-line, so an unmarked bundle reads as a complete one."""
    repo = _repo(tmp_path, {"docker-compose.yml": "s" * 50_000})
    bundle, stats = ac.build_bundle(repo, max_chars=1_000)
    assert bundle.startswith("=" * 5)
    assert "BUNDLE TRUNCATED" in bundle
    assert stats["truncated"] is True
    assert len(bundle) > 1_000        # the marker is appended after the slice


def test_build_bundle_counts_only_files_whose_text_reached_the_bundle(tmp_path):
    """An empty or unreadable config file is classified, then skipped by the
    parts loop. Counting it makes the footer claim coverage that is not there
    (coderay-q2r.27)."""
    repo = _repo(tmp_path, {"docker-compose.yml": "services: {}\n",
                            "docker-compose.override.yml": ""})
    bundle, stats = ac.build_bundle(repo)
    assert stats["config_files"] == 1
    assert stats["config_files_found"] == 2
    assert bundle.count("===== PROCESS DECLARATION") == 1


def test_redact_carries_a_kubernetes_env_name_across_to_its_value():
    """coderay-q2r.30. k8s splits an env var over two sibling lines.

    `- name: API_TOKEN` / `value: <secret>`: the sensitive word is on the name
    line, so a per-line key match never sees it and `value` matches nothing.
    Deployment manifests are core input here, not an edge case. The LOG_LEVEL
    pair is the control -- redacting every `value:` would eat the topology.
    """
    manifest = ("kind: Deployment\n"
                "spec:\n"
                "  containers:\n"
                "  - name: api\n"
                "    image: acme/api:1.2\n"
                "    env:\n"
                "    - name: API_TOKEN\n"
                "      value: sk-live-LEAKED\n"
                "    - name: LOG_LEVEL\n"
                "      value: debug\n")
    out = ac._redact(manifest)
    assert "sk-live-LEAKED" not in out
    assert "value: debug" in out          # an ordinary env var keeps its value
    assert "name: api" in out             # the container name is topology
    assert "image: acme/api:1.2" in out


def test_redact_does_not_treat_a_plain_name_key_as_an_env_pair():
    """`name:` appears all over a manifest; only an env entry pairs it with
    `value:`. A stray value after an unrelated name must not be swallowed."""
    out = ac._redact("metadata:\n  name: my-app\nspec:\n  replicas: 3\n")
    assert out == "metadata:\n  name: my-app\nspec:\n  replicas: 3\n"


def test_sdk_evidence_carries_the_path_and_the_sdk_but_not_the_source(tmp_path):
    """coderay-q2r.31. The pattern matches constructors like `new Stripe(...)`.

    A token hardcoded in one would ship to the LLM verbatim, and _redact cannot
    catch it -- there is no key=value shape to key off. The evidence the section
    exists to give is that a file talks to a service, which survives here.
    """
    import subprocess
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "pay.ts": 'import Stripe from "stripe";\nconst s = new Stripe("sk_live_HARDCODED");\n',
    })
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", repo] + cmd, check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "x"], check=True)

    bundle, stats = ac.build_bundle(repo)
    assert "sk_live_HARDCODED" not in bundle
    assert "pay.ts:2: Stripe" in bundle    # the edge is still reported
    assert stats["sdk_lines"] == 2 and stats["sdk_unavailable"] is None


def test_build_bundle_refuses_a_config_file_symlinked_out_of_the_repo(tmp_path):
    """coderay-q2r.28. The repo is untrusted; a config file can be a symlink."""
    outside = tmp_path / "outside.env"
    outside.write_text("OUTSIDE-SECRET-CONTENT\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"README.md": "# hi\n"})
    os.symlink(outside, os.path.join(repo, "docker-compose.yml"))

    bundle, _stats = ac.build_bundle(repo)
    assert "OUTSIDE-SECRET-CONTENT" not in bundle


def test_build_bundle_refuses_a_config_file_symlinked_to_an_in_repo_credential_file(tmp_path):
    """coderay-q2r.56. `docker-compose.yml -> id_rsa` resolves inside the
    repo, so within_repo let the key body through. A bare key line has no
    `key=value` shape, so _redact cannot catch it either; only refusing the
    read does."""
    repo = _repo(tmp_path / "repo", {"README.md": "# hi\n",
                                     "id_rsa": "BEGIN-HUNTER2-PRIVATE-KEY\n"})
    os.symlink(os.path.join(repo, "id_rsa"), os.path.join(repo, "docker-compose.yml"))

    bundle, _stats = ac.build_bundle(repo)
    assert "HUNTER2" not in bundle


def test_build_bundle_skips_a_virtualenv_named_env_but_still_reads_examples(tmp_path):
    """PR #30 review. SKIP_DIRS is the shared set plus .yarn, minus docs and
    examples, which this crawler has always read for compose files."""
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services:\n  api:\n    image: api\n",
        "env/lib/python3.12/site-packages/pkg/docker-compose.yml": "services:\n  ignored:\n    image: x\n",
        "examples/docker-compose.yml": "services:\n  example:\n    image: y\n",
    })
    bundle, _stats = ac.build_bundle(repo)
    assert "ignored" not in bundle
    assert "example:" in bundle


def test_build_bundle_refuses_a_credential_named_manifest_it_walked_to(tmp_path):
    """PR #30 review. The opt-in for a real .env must not pass every
    credential-named file the classifier accepts: a bare key body in
    deploy/credentials.yaml has no key: value shape for _redact to catch."""
    repo = _repo(tmp_path, {
        "README.md": "# hi\n",
        "deploy/credentials.yaml": "BEGIN-HUNTER2-PRIVATE-KEY\n",
        ".env": "TOKEN=hunter2\n",
        "infra/prod.tfvars": 'db_password = "hunter2"\nregion = "us-east-1"\n',
    })
    bundle, stats = ac.build_bundle(repo)
    assert "HUNTER2" not in bundle
    assert stats["env_vars"] == 1                 # .env is still read for names
    assert "region" in bundle and "hunter2" not in bundle   # .tfvars still read, redacted


def test_sdk_evidence_reads_go_import_paths(tmp_path):
    """coderay-5wu.14. A Go import is a module path, not a package name, so it
    needs its own pattern; the evidence is the client's name, drawn from the
    path (the repo segment, or the owner when the repo is a generic sdk-go)."""
    import subprocess
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "store.go": ('package hub\n\nimport (\n\t"database/sql"\n\t"modernc.org/sqlite"\n'
                     '\t"github.com/stripe/stripe-go/v79"\n\t"github.com/acme/clients/sdk-go/pkg/x"\n'
                     '\tredis "github.com/redis/go-redis/v9"\n\t"cloud.google.com/go/storage"\n'
                     '\t"google.golang.org/grpc"\n\t"github.com/google/uuid"\n)\n'),
    })
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", repo] + cmd, check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "x"], check=True)
    bundle, stats = ac.build_bundle(repo)
    for line in ("store.go:5: sqlite", "store.go:6: stripe-go", "store.go:7: acme",
                 "store.go:8: go-redis", "store.go:9: storage", "store.go:10: grpc"):
        assert line in bundle, line
    assert "uuid" not in bundle and "database/sql" not in bundle
    assert stats["sdk_lines"] == 6


@pytest.mark.parametrize("path,name", [
    ("github.com/stripe/stripe-go/v79", "stripe-go"),
    ("github.com/aws/aws-sdk-go-v2/service/s3", "aws-sdk-go-v2"),
    ("github.com/acme/clients/sdk-go/pkg/x", "acme"),
    ("modernc.org/sqlite", "sqlite"),
    ("cloud.google.com/go/storage", "storage"),
    ("google.golang.org/grpc", "grpc"),
    ("github.com/nats-io/nats.go", "nats.go"),
])
def test_go_sdk_name_is_the_client_not_the_host(path, name):
    assert ac.go_sdk_name(path) == name
