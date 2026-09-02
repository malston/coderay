import json

import pytest

from crack.analyses.architecture import arch_crawl as ac


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
    deliberately not fixed here, because arch_crawl.py is copied verbatim. When
    upstream fixes it this test fails, which is the signal to re-port and
    invert it.
    """
    assert ac._classify(rel) is None


@pytest.mark.parametrize("rel", ["k8s/api.yaml", "manifests/web.yml", "charts/api/values.yaml"])
def test_classify_reads_a_manifest_directory_at_the_repo_root(rel):
    """Was the second half of coderay-q2r.10, fixed upstream and re-ported at
    pin 34f0ad2, alongside the same fix to backend's crawl (coderay-q2r.7).

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


def test_only_dotenv_files_have_their_values_stripped(tmp_path):
    """Known defect, tracked as coderay-q2r.14.

    _env_names keeps names only, and the bundle header says "values omitted",
    but that rule reaches exactly one of the seven file kinds the crawl
    collects. compose, k8s, gateway and iac files are appended whole, values
    included, and all four are ordinary places to find live credentials. The
    bundle goes to a third-party LLM API.

    Inherited from the port source and deliberately not fixed here, because
    arch_crawl.py is copied verbatim. This test asserts the leak, so it fails
    the moment the leak is closed -- which is the signal to re-port and invert
    it. Read a pass here as "the defect is still present", never as "safe".
    """
    repo = _repo(tmp_path, {
        ".env": "DOTENV_SECRET=stripped-value\n",
        "infra/prod.tfvars": 'db_password = "leaked-from-tfvars"\n',
        "docker-compose.yml": "services:\n  api:\n    environment:\n"
                              "      STRIPE_KEY: leaked-from-compose\n",
        "deploy/k8s/secret.yaml": "kind: Secret\ndata:\n  pw: leaked-from-k8s\n",
        "fly.toml": '[env]\nAPI_TOKEN = "leaked-from-fly"\n',
    })
    bundle, _stats = ac.build_bundle(repo)

    # The one path that honours the promise.
    assert "DOTENV_SECRET" in bundle
    assert "stripped-value" not in bundle

    # The four that do not.
    for leaked in ("leaked-from-tfvars", "leaked-from-compose",
                   "leaked-from-k8s", "leaked-from-fly"):
        assert leaked in bundle, f"{leaked} no longer leaks -- see coderay-q2r.14"


def test_sdk_imports_report_zero_outside_a_git_checkout(tmp_path):
    """Known defect, tracked as coderay-q2r.15.

    _sdk_grep catches every exception and returns "", so `git grep` failing
    with exit 128 (not a repository) is indistinguishable from it succeeding
    with no matches. A tarball export loses the whole evidence class that
    proves a connection is live, and nothing in the stats says so.

    The repo below holds a real SDK import that a working `git grep` would
    find, which is what separates the two cases; tmp_path is not a git
    checkout, so the count is zero anyway. Inherited from the port source and
    deliberately not fixed here.
    """
    repo = _repo(tmp_path, {
        "docker-compose.yml": "services: {}\n",
        "src/pay.ts": "import Stripe from 'stripe';\n",
    })
    _bundle, stats = ac.build_bundle(repo)
    assert stats["sdk_lines"] == 0


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

    assert stats == {"config_files": 4, "env_vars": 2, "deps": 2,
                     "integrations": 0, "sdk_lines": 0}
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


def test_build_bundle_caps_the_total_size(tmp_path):
    repo = _repo(tmp_path, {"docker-compose.yml": "s" * 50_000})
    bundle, _stats = ac.build_bundle(repo, max_chars=1_000)
    assert len(bundle) == 1_000
