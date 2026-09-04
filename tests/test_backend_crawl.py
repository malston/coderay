import pytest

from crack.analyses.backend import backend_crawl as bc


@pytest.mark.parametrize("rel,layer", [
    ("app/urls.py", "route"),
    ("api/routes/user.ts", "route"),
    ("app/pages/api/login.ts", "route"),
    ("app/middleware.py", "middleware"),
    ("app/decorators.py", "middleware"),
    ("app/views/message.py", "handler"),
    ("app/controllers/user.rb", "handler"),
    ("app/actions/send.py", "service"),
    ("app/services/billing.py", "service"),
    ("app/models/user.py", "database"),
    ("app/models.py", "database"),
    ("app/serializers/user.py", "response"),
])
def test_classify_maps_a_path_to_its_layer(rel, layer):
    assert bc.classify(rel) == layer


@pytest.mark.parametrize("rel", [
    "README.md", "app/style.css", "app/views/message.test.py",
    "app/views/user.spec.ts", "app/util.py",
])
def test_classify_returns_none_for_a_non_layer_file(rel):
    assert bc.classify(rel) is None


@pytest.mark.parametrize("rel,layer", [
    ("pages/api/login.ts", "route"), ("routes/user.js", "route"),
    ("views/home.py", "handler"), ("models/user.py", "database"),
    ("services/billing.py", "service"),
])
def test_classify_reads_a_layer_directory_at_the_repo_root(rel, layer):
    """Was coderay-q2r.7, fixed upstream and re-ported at pin 34f0ad2.

    Every directory rule matches on its surrounding slashes, and
    os.path.relpath never produces a leading one, so a repo keeping
    `pages/api/` or `routes/` at its root used to match nothing. classify now
    prepends the leading slash. The nested form must keep working too, which
    is what separates the fix from one that merely stripped the slashes.
    """
    assert bc.classify(rel) == layer
    assert bc.classify("src/" + rel) == layer


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_build_bundle_counts_every_layer_and_includes_the_spine(tmp_path):
    repo = _repo(tmp_path, {
        "app/urls.py": "urlpatterns = []\n",
        "app/middleware.py": "class Mw: pass\n",
        "app/views/message.py": "def send(): pass\n",
        "app/models.py": "class User: pass\n",
    })
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {"route": 1, "middleware": 1, "handler": 1, "database": 1}
    assert "LAYER FILE COUNTS" in bundle
    assert "LAYER ROUTE: app/urls.py" in bundle
    assert "urlpatterns = []" in bundle
    assert stats["included"] == 4


def test_build_bundle_skips_ignored_directories(tmp_path):
    repo = _repo(tmp_path, {
        "app/urls.py": "ok\n",
        "tests/urls.py": "ignored\n",
        "node_modules/pkg/routes/a.js": "ignored\n",
        "migrations/urls.py": "ignored\n",
    })
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"]["route"] == 1
    assert "ignored" not in bundle


def test_build_bundle_returns_an_empty_bundle_for_a_repo_with_no_backend(tmp_path):
    repo = _repo(tmp_path, {"README.md": "# hi\n", "index.html": "<p>x</p>\n"})
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {}
    assert stats["included"] == 0


def test_build_bundle_caps_total_size(tmp_path):
    repo = _repo(tmp_path, {f"app/routes/r{i}.py": "x" * 2000 for i in range(20)})
    bundle, stats = bc.build_bundle(repo, max_chars=6000)
    assert len(bundle) <= 6000
    assert stats["counts"]["route"] == 20
    assert stats["included"] < 20


def test_build_bundle_samples_handlers_and_prefers_core_names(tmp_path):
    """The sample must be chosen by CORE_HINTS priority, not by filename order.

    Every candidate here sorts alphabetically BEFORE the core-named file, so a
    build_bundle that ignored _priority and sorted on the name alone would pick
    aaa.py and miss message.py. That is the whole point: the trace pass needs
    the file naming the core endpoint, and it is rarely first alphabetically.
    """
    files = {f"app/views/aaa{i}.py": "pass\n" for i in range(20)}
    files["app/views/message.py"] = "def send(): pass\n"
    repo = _repo(tmp_path, files)
    bundle, stats = bc.build_bundle(repo, per_layer_sample=1)
    assert stats["counts"]["handler"] == 21
    assert stats["included"] == 1
    assert "app/views/message.py" in bundle
    assert "app/views/aaa0.py" not in bundle


def test_build_bundle_refuses_a_symlink_escaping_the_repo(tmp_path):
    """coderay-q2r.54: a checked-in urls.py that is a symlink to a file outside
    the repo must not be read into the bundle."""
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE SECRET\n")
    repo = _repo(tmp_path / "repo", {"app/views/a.py": "pass\n"})
    (tmp_path / "repo" / "app" / "urls.py").symlink_to(outside)
    bundle, stats = bc.build_bundle(repo)
    assert "OUTSIDE SECRET" not in bundle
    assert stats["counts"].get("route", 0) == 0


def test_build_bundle_skips_a_symlink_that_renames_a_credential_file(tmp_path):
    """coderay-q2r.54: app/urls.py -> ../.env carries a source name but a
    credential body; the target's own name has to pass the skip list."""
    repo = _repo(tmp_path, {".env": "TOKEN=hunter2\n", "app/views/a.py": "pass\n"})
    (tmp_path / "app" / "urls.py").symlink_to(tmp_path / ".env")
    bundle, stats = bc.build_bundle(repo)
    assert "hunter2" not in bundle
    assert stats["counts"].get("route", 0) == 0


def test_build_bundle_includes_a_long_file_whole(tmp_path):
    """coderay-q2r.54: the budget is enforced by how many files are included;
    a file that fits arrives whole."""
    body = "x" * 50_000 + "\nTAIL_MARKER\n"
    repo = _repo(tmp_path, {"app/urls.py": body})
    bundle, _ = bc.build_bundle(repo)
    assert "TAIL_MARKER" in bundle


def test_build_bundle_drops_an_oversized_file_whole(tmp_path):
    """coderay-q2r.54: list_files' per-file size cap drops the file from the
    bundle and its count."""
    repo = _repo(tmp_path, {"app/urls.py": "x" * 600_000, "app/views/a.py": "pass\n"})
    bundle, stats = bc.build_bundle(repo)
    assert "LAYER ROUTE" not in bundle
    assert stats["counts"].get("route", 0) == 0


def test_build_bundle_skips_a_file_it_cannot_decode(tmp_path):
    """coderay-q2r.54: an undecodable file is left out of the bundle; it still
    counts toward its layer."""
    repo = _repo(tmp_path, {"app/views/a.py": "pass\n"})
    (tmp_path / "app" / "urls.py").write_bytes(b"\xff\xfe not utf-8")
    bundle, stats = bc.build_bundle(repo)
    assert "LAYER ROUTE" not in bundle
    assert stats["counts"]["route"] == 1


def test_build_bundle_keeps_an_uppercase_source_extension(tmp_path):
    """coderay-q2r.54: classify() lowercases the path, so the walk must accept
    `.PY`/`.PHP` too or a route file vanishes from both the bundle and the count."""
    repo = _repo(tmp_path, {"app/URLS.PY": "urlpatterns = []\n"})
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"]["route"] == 1
    assert "urlpatterns = []" in bundle


def test_build_bundle_skips_a_virtualenv_named_env(tmp_path):
    """coderay-q2r.59. `python -m venv env` in the target put Django's own
    urls.py in the route count; SKIP_DIRS is DEFAULT_SKIP_DIR plus the
    backend's extras, not a hand-written subset of it."""
    repo = _repo(tmp_path, {
        "app/urls.py": "ok\n",
        "env/lib/python3.12/site-packages/django/contrib/admin/urls.py": "ignored\n",
        "spec/controllers/users_controller_spec.rb": "ignored\n",
    })
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {"route": 1}
    assert "ignored" not in bundle


def test_classify_treats_a_rails_spec_as_a_test():
    """coderay-q2r.59. `_spec.rb` is the RSpec convention and was not in the
    test-marker tuple, so a spec beside the controllers counted as a handler."""
    assert bc.classify("app/controllers/users_controller_spec.rb") is None
    assert bc.classify("app/controllers/users_controller.rb") == "handler"


def test_build_bundle_gives_every_layer_a_file_before_a_spine_file_takes_the_rest(tmp_path):
    """coderay-q2r.58. Spine files went first and in full, so one 499k routes
    file spent most of the 650k budget and the sampled layers were dropped
    while the header still counted them. Selection is round-robin across the
    layers; a file that does not fit is dropped whole, never cut."""
    files = {"app/routes/bundle.js": "r" * 499_000}
    for layer_dir in ("views", "services", "models"):
        for i in range(18):
            files[f"app/{layer_dir}/f{i}.py"] = f"# {layer_dir} {i}\n" + "x" * 5_000
    repo = _repo(tmp_path, files)
    bundle, stats = bc.build_bundle(repo)
    assert stats["counts"] == {"route": 1, "handler": 18, "service": 18, "database": 18}
    assert len(bundle) <= 650_000
    assert "LAYER ROUTE: app/routes/bundle.js" in bundle
    shares = [bundle.count(f"LAYER {layer}: ") for layer in ("HANDLER", "SERVICE", "DATABASE")]
    assert min(shares) >= 1 and max(shares) - min(shares) <= 1, shares
    # Grouped emission: the prompts see the layers in the same order as before.
    assert bundle.index("LAYER ROUTE:") < bundle.index("LAYER HANDLER:") < bundle.index("LAYER DATABASE:")


def test_classify_keeps_a_non_rails_file_whose_name_contains_spec():
    """PR #30 review. The RSpec marker is `_spec.rb`; openapi_spec.py is source."""
    assert bc.classify("app/services/openapi_spec.py") == "service"
    assert bc.classify("src/routes/openapi_spec.ts") == "route"


def test_build_bundle_samples_from_readable_files_not_from_the_first_n_paths(tmp_path):
    """PR #30 review. The sample was sliced to per_layer_sample paths before any
    file was read, so empty files took every slot and a readable file ranked
    after them was never a candidate."""
    files = {f"app/views/a{i:02d}.py": "" for i in range(18)}
    files["app/views/zeta.py"] = "def z(): pass\n"
    repo = _repo(tmp_path, files)
    bundle, stats = bc.build_bundle(repo)
    assert stats == {"counts": {"handler": 19}, "included": 1}
    assert "app/views/zeta.py" in bundle
