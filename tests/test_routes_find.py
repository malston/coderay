import os

import pytest

from crawl.analyses.interfaces import routes_find as rf


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
    text, resolved, _ = rf.read_files(repo, ["pages/api/login.ts"])
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
    text, resolved, _ = rf.read_files(repo, ["../secrets.env"])
    assert resolved == []
    assert "real-looking-value" not in text


def test_read_files_refuses_a_symlink_that_points_out_of_the_repository(tmp_path):
    outside = tmp_path / "secrets.env"
    outside.write_text("AWS_SECRET_ACCESS_KEY=real-looking-value\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"pages/api/login.ts": "x\n"})
    os.symlink(outside, os.path.join(repo, "linked.env"))

    text, resolved, _ = rf.read_files(repo, ["linked.env"])
    assert resolved == []
    assert "real-looking-value" not in text


def test_read_files_still_reads_an_ordinary_file_inside_the_repository(tmp_path):
    """The containment check must not refuse the paths the analysis is for."""
    repo = _repo(tmp_path / "repo", {"src/handlers/login.ts": "export default login\n"})
    text, resolved, _ = rf.read_files(repo, ["src/handlers/login.ts"])
    assert resolved == ["src/handlers/login.ts"]
    assert "export default login" in text


def test_crawl_routes_refuses_a_route_file_symlinked_out_of_the_repo(tmp_path):
    """coderay-q2r.28. read_files already refuses paths the MODEL names; the
    same rule was missing where the path comes from the repo itself.

    A checked-in `urls.py` that is a symlink is read like any other file and
    its contents reach the prompt. `real.rb` keeps the crawl non-empty so this
    fails on the leak rather than on an empty bundle.
    """
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE-SECRET-CONTENT\n", encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"config/routes.rb": "Rails.routes\n"})
    os.makedirs(os.path.join(repo, "app"), exist_ok=True)
    os.symlink(outside, os.path.join(repo, "app", "urls.py"))

    routes, files, kept = rf.crawl_routes(repo)
    assert "OUTSIDE-SECRET-CONTENT" not in routes
    assert "app/urls.py" in files          # still discovered, deliberately unread
    assert kept == ["config/routes.rb"]


def test_crawl_routes_refuses_a_route_file_symlinked_to_an_in_repo_credential_file(tmp_path):
    """coderay-q2r.56. within_repo follows the link and finds the target inside
    the repo, so `app/urls.py -> ../.env` passed and the .env body reached the
    prompt. The target's own name has to pass the credential skip too, the way
    list_files already demands (coderay-q2r.52)."""
    repo = _repo(tmp_path / "repo", {"config/routes.rb": "Rails.routes\n",
                                     ".env": "TOKEN=hunter2\n"})
    os.makedirs(os.path.join(repo, "app"), exist_ok=True)
    os.symlink(os.path.join(repo, ".env"), os.path.join(repo, "app", "urls.py"))

    routes, files, kept = rf.crawl_routes(repo)
    assert "hunter2" not in routes
    assert "app/urls.py" in files
    assert kept == ["config/routes.rb"]


def test_read_files_refuses_a_symlink_to_an_in_repo_credential_file(tmp_path):
    """coderay-q2r.56. The model names a source-looking path; the repo made it a
    symlink to its own .env."""
    repo = _repo(tmp_path / "repo", {"pages/api/login.ts": "x\n", ".env": "TOKEN=hunter2\n"})
    os.makedirs(os.path.join(repo, "src"), exist_ok=True)
    os.symlink(os.path.join(repo, ".env"), os.path.join(repo, "src", "config.ts"))

    text, resolved, _ = rf.read_files(repo, ["src/config.ts"])
    assert resolved == []
    assert "hunter2" not in text


def test_read_files_refuses_a_credential_named_path_the_model_picked(tmp_path):
    """coderay-q2r.56 review. The model names the paths here, and it has been
    reading the untrusted repo, so it may name a dotenv file itself; no symlink
    needed. `.env` resolves to `config/.env` by suffix and is refused there;
    `settings.py` resolves the same way and is read, so the suffix path is live."""
    repo = _repo(tmp_path / "repo", {"pages/api/login.ts": "x\n",
                                     "config/.env": "TOKEN=hunter2\n",
                                     "config/settings.py": "DEBUG = True\n"})

    text, resolved, _ = rf.read_files(repo, ["config/.env", ".env", "settings.py"])
    assert resolved == ["config/settings.py"]
    assert "hunter2" not in text


def test_find_route_files_skips_a_virtualenv_named_env(tmp_path):
    """PR #30 review. The hand-written SKIP_DIRS missed `env`, so a checked-out
    virtualenv put Django's own urls.py in the crawl as a priority-0 aggregator."""
    repo = _repo(tmp_path / "repo", {
        "app/urls.py": "ok\n",
        "env/lib/python3.12/site-packages/django/contrib/admin/urls.py": "ignored\n",
        ".storybook/routes.ts": "ignored\n",
    })
    assert rf.find_route_files(repo) == ["app/urls.py"]


def test_read_files_suffix_match_starts_at_a_path_segment(tmp_path):
    """coderay-q2r.61. An unanchored endswith lets `env` resolve to `.env.example`,
    `y` to the first file ending in y, and an empty key to the first file in walk
    order, so the diagram is drawn from the wrong file. The model's path must
    match whole segments from the right."""
    repo = _repo(tmp_path / "repo", {"config/.env.example": "TOKEN=\n",
                                     "api/users.py": "def users(): pass\n"})
    assert rf.read_files(repo, ["env"])[1] == []
    for blank in ("", "`", "/"):
        assert rf.read_files(repo, [blank])[1] == []
    assert rf.read_files(repo, ["sers.py"])[1] == []
    assert rf.read_files(repo, ["users.py"])[1] == ["api/users.py"]
    assert rf.read_files(repo, ["api/users.py"])[1] == ["api/users.py"]


def test_read_files_reports_every_named_path_it_did_not_read(tmp_path):
    """coderay-5wu.1. The third value is what the card needs: every named path
    that was not read, whatever the reason (missing, empty, past the file cap,
    over the size budget, refused), in the order named. A path resolved by
    suffix counts as read."""
    files = {"api/users.py": "def users(): pass\n", "api/empty.py": "  \n", ".env": "T=1\n"}
    files.update({f"h{i}.py": f"h = {i}\n" for i in range(8)})
    repo = _repo(tmp_path / "repo", files)
    named = ["users.py", "api/empty.py", ".env", "gone.py"] + [f"h{i}.py" for i in range(8)]
    text, resolved, skipped = rf.read_files(repo, named)
    # The cap counts positions in the model's list, so h4..h7 are never looked at.
    assert resolved == ["api/users.py", "h0.py", "h1.py", "h2.py", "h3.py"]
    assert skipped == ["api/empty.py", ".env", "gone.py", "h4.py", "h5.py", "h6.py", "h7.py"]


def test_read_files_reports_the_paths_cut_by_the_size_budget(tmp_path):
    repo = _repo(tmp_path / "repo", {f"b{i}.py": "x" * 50 + "\n" for i in range(4)})
    text, resolved, skipped = rf.read_files(repo, [f"b{i}.py" for i in range(4)], max_chars=400)
    assert resolved == ["b0.py", "b1.py"] and skipped == ["b2.py", "b3.py"]
