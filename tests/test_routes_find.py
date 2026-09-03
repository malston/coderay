import os

import pytest

from crack.analyses.interfaces import routes_find as rf


@pytest.mark.parametrize("rel", [
    "config/routes.rb", "app/urls.py", "src/routes.ts", "src/router.ts",
    "server/routes.js", "schema.graphql", "api/user.proto",
    "src/trpc/_router.ts", "pages/api/login.ts", "src/pages/api/login.tsx",
    "app/users/route.ts", "cmd/server/main.go",
])
def test_is_route_file_recognises_a_framework_convention(rel):
    assert rf.is_route_file(rel) is True


@pytest.mark.parametrize("rel", [
    "README.md", "src/index.ts", "src/routes.test.ts", "src/router.spec.ts",
    "app/urls_test.py", "src/routes.stories.tsx", "app/page.tsx",
])
def test_is_route_file_rejects_a_non_surface_file(rel):
    assert rf.is_route_file(rel) is False


@pytest.mark.parametrize("rel", ["pages/api/login.ts", "app/users/route.ts", "cmd/server/main.go"])
def test_is_route_file_reads_a_convention_directory_at_the_repo_root(rel):
    """Was the interfaces half of the fix in upstream 4a74f7e, at pin 34f0ad2.

    Next.js keeps pages/api/ and app/ at the repo root and Go keeps cmd/ there,
    which is the layout each framework generates. The rules match on their
    surrounding slashes, so before the fix FindRoutes refused to run at all on
    a stock Next.js app. Both the root and nested forms must work, which is
    what separates the fix from one that merely stripped the slashes.
    """
    assert rf.is_route_file(rel) is True
    assert rf.is_route_file("src/" + rel) is True


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_find_route_files_skips_vendor_and_test_directories(tmp_path):
    repo = _repo(tmp_path, {
        "config/routes.rb": "Rails.routes\n",
        "node_modules/pkg/routes.ts": "ignored\n",
        "tests/routes.ts": "ignored\n",
        "docs/routes.ts": "ignored\n",
    })
    assert rf.find_route_files(repo) == ["config/routes.rb"]


def test_crawl_routes_puts_aggregators_before_single_handlers(tmp_path):
    """A cap must trim single Next.js handlers, not the route manifest.

    The manifest sorts last alphabetically here, so a plain sorted() would put
    it after both handlers. That is the input that separates the priority sort
    from no sort at all.
    """
    repo = _repo(tmp_path, {
        "pages/api/aaa.ts": "export default aaa\n",
        "pages/api/bbb.ts": "export default bbb\n",
        "zzz/urls.py": "urlpatterns = []\n",
    })
    routes, files, kept = rf.crawl_routes(repo)
    assert kept == files          # nothing dropped, so read == found
    assert routes.index("zzz/urls.py") < routes.index("pages/api/aaa.ts")


def test_crawl_routes_caps_the_total_size(tmp_path):
    repo = _repo(tmp_path, {
        "zzz/urls.py": "u" * 5_000,
        "pages/api/big.ts": "b" * 5_000,
    })
    routes, files, kept = rf.crawl_routes(repo, max_chars=5_200)
    # kept is the list of files that reached the bundle, so the caller can
    # report provenance honestly (coderay-q2r.24).
    assert kept == ["zzz/urls.py"]
    assert len(files) == 2
    # The aggregator is the one kept, not whichever came first on disk.
    assert "zzz/urls.py" in routes and "pages/api/big.ts" not in routes


def test_read_files_resolves_a_path_by_suffix_when_the_exact_path_is_wrong(tmp_path):
    """The model often names a path that is right but for a leading directory."""
    repo = _repo(tmp_path, {"apps/web/pages/api/login.ts": "export default login\n"})
    text, resolved = rf.read_files(repo, ["pages/api/login.ts"])
    assert resolved == ["apps/web/pages/api/login.ts"]
    assert "export default login" in text


def test_read_files_refuses_a_path_that_climbs_out_of_the_repository(tmp_path):
    """coderay-q2r.16. The path list is LLM output, and the LLM is reading the
    target repository's own untrusted files.

    A prompt injection that names ../secrets.env would otherwise get the file
    read into the sequence-diagram prompt and echoed into the report. The
    escaping path must resolve to a real, readable file, or the test would pass
    against a broken implementation for the wrong reason.
    """
    outside = tmp_path / "secrets.env"
    outside.write_text("AWS_SECRET_ACCESS_KEY=real-looking-value\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"pages/api/login.ts": "export default login\n"})

    assert os.path.isfile(os.path.join(repo, "../secrets.env"))  # the escape is real
    text, resolved = rf.read_files(repo, ["../secrets.env"])
    assert resolved == []
    assert "real-looking-value" not in text


def test_read_files_refuses_a_symlink_that_points_out_of_the_repository(tmp_path):
    outside = tmp_path / "secrets.env"
    outside.write_text("AWS_SECRET_ACCESS_KEY=real-looking-value\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"pages/api/login.ts": "x\n"})
    os.symlink(outside, os.path.join(repo, "linked.env"))

    text, resolved = rf.read_files(repo, ["linked.env"])
    assert resolved == []
    assert "real-looking-value" not in text


def test_read_files_still_reads_an_ordinary_file_inside_the_repository(tmp_path):
    """The containment check must not refuse the paths the analysis is for."""
    repo = _repo(tmp_path / "repo", {"src/handlers/login.ts": "export default login\n"})
    text, resolved = rf.read_files(repo, ["src/handlers/login.ts"])
    assert resolved == ["src/handlers/login.ts"]
    assert "export default login" in text
