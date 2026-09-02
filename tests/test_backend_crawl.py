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
