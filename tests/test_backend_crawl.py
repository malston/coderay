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


@pytest.mark.parametrize("rel", [
    "pages/api/login.ts", "routes/user.js", "views/home.py",
    "models/user.py", "services/billing.py",
])
def test_classify_misses_a_layer_directory_at_the_repo_root(rel):
    """Known limitation, tracked as coderay-q2r.7.

    Every directory rule matches on a leading slash, and os.path.relpath
    never produces one, so a layer directory at the repository root is
    skipped. Inherited from the port source and deliberately not fixed
    here, because backend_crawl.py is copied verbatim. When upstream fixes
    it this test fails, which is the signal to re-port and invert it.
    """
    assert bc.classify(rel) is None


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
    files = {f"app/views/zz{i}.py": "pass\n" for i in range(20)}
    files["app/views/message.py"] = "def send(): pass\n"
    repo = _repo(tmp_path, files)
    bundle, stats = bc.build_bundle(repo, per_layer_sample=2)
    assert stats["counts"]["handler"] == 21
    assert "app/views/message.py" in bundle
    assert stats["included"] == 2
