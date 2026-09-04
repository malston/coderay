import os

import pytest

from crawl.analyses.interfaces import routes_find as rf


@pytest.mark.parametrize("rel", [
    "config/routes.rb", "app/urls.py", "src/routes.ts", "src/router.ts",
    "server/routes.js", "schema.graphql", "api/user.proto",
    "src/trpc/_router.ts", "pages/api/login.ts", "src/pages/api/login.tsx",
    "app/users/route.ts",
])
def test_is_route_file_recognises_a_framework_convention(rel):
    assert rf.is_route_file(rel) is True


@pytest.mark.parametrize("rel", [
    "README.md", "src/index.ts", "src/routes.test.ts", "src/router.spec.ts",
    "app/urls_test.py", "src/routes.stories.tsx", "app/page.tsx",
])
def test_is_route_file_rejects_a_non_surface_file(rel):
    assert rf.is_route_file(rel) is False


@pytest.mark.parametrize("rel", ["pages/api/login.ts", "app/users/route.ts"])
def test_is_route_file_reads_a_convention_directory_at_the_repo_root(rel):
    """Was the interfaces half of the fix in upstream 4a74f7e, at pin 34f0ad2.

    Next.js keeps pages/api/ and app/ at the repo root, which is the layout the
    framework generates. The rules match on their surrounding slashes, so
    before the fix FindRoutes refused to run at all on a stock Next.js app.
    Both the root and nested forms must work, which is what separates the fix
    from one that merely stripped the slashes.
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


# coderay-5wu.12: Go has no route-file name. A file is part of the surface when
# it registers handlers, wherever it sits.
@pytest.mark.parametrize("text,count", [
    ('mux := http.NewServeMux()\nmux.HandleFunc("/api/x", h)\nmux.Handle("/", fs)\n', 3),
    ('r := chi.NewRouter()\nr.Get("/users", list)\nr.Post("/users", create)\nr.Mount("/v2", sub)\n', 4),
    ('g := gin.Default()\ng.GET("/ping", ping)\n', 2),
    ('e := echo.New()\ne.POST("/login", login)\n', 2),
    ('token := r.Header.Get("X-Token")\nresp.Header.Get("ETag")\n', 0),
    ('func main() { cmd.Execute() }\n', 0),
    ('r.Options("/x", h)\nr.Head("/y", h)\ne.Any("/z", h)\ng.OPTIONS("/o", h)\ng.HEAD("/h", h)\n', 5),
    ('// mux.HandleFunc("/old", h)\n// r.Get("/gone", h)\nmux.HandleFunc("/live", h)\n', 1),
    ('func NewRouter(cfg Config) *Router { return nil }\nfunc (m *Mux) HandleFunc(p string, h Handler) {}\n', 1),
    ('r := mux.NewRouter()\nr.HandleFunc("/x", h)\n', 2),
    ('g := gin.New()\ng.PUT("/a", h)\ng.DELETE("/b", h)\ng.PATCH("/c", h)\n', 4),
    ('r := chi.NewRouter()\nr.Put("/a", h)\nr.Delete("/b", h)\nr.Patch("/c", h)\nr.Route("/u", fn)\nr.Group("/api")\n', 6),
    ('r.Get(\n    "/users",\n    list,\n)\n', 1),
    # a typed HTTP client is the heuristic's known false positive; deliberate
    ('c.Get("/users", &out)\nc.Post("/users", body, &out)\n', 2),
    # Go 1.22 method patterns, gorilla Path chains, gRPC service registration
    ('mux.Handle("GET /users", h)\nmux.HandleFunc("POST /users", h)\n', 2),
    ('r.Path("/users").Methods("GET").Handler(h)\n', 1),
    ('s := grpc.NewServer()\npb.RegisterUserServiceServer(s, &srv{})\n', 2),
    # a URL literal is not a comment; a block comment is one
    ('u := "https://acme.com"; mux.Handle("/", h)\n', 1),
    ('/* r.Get("/old", h)\nr.Get("/old2", h) */\nr.Get("/live", h)\n', 1),
])
def test_go_route_registrations_counts_handler_registrations_only(text, count):
    """`r.Header.Get("X-Token")` reads a header; `r.Get("/users", h)` registers
    a route. The path literal after the call is what tells them apart."""
    assert rf.go_route_registrations(text) == count


def test_find_route_files_reads_go_files_that_register_routes(tmp_path):
    """Go route files are found by content, so a Cobra subcommand under cmd/ is
    not on the surface and the file that registers every route is; test
    scaffolding (a _test.go, a fixture directory, a testhelpers.go) stays out
    even when it starts a mock server."""
    repo = _repo(tmp_path / "repo", {
        "pkg/hub/server.go": 'mux.HandleFunc("/api/a", a)\nmux.HandleFunc("/api/b", b)\n',
        "pkg/hub/db.go": "func open() {}\n",
        "cmd/tool/convert.go": "func run() { cmd.Execute() }\n",
        "cmd/bridge/main.go": "m := http.NewServeMux()\nm.Handle(path, h)\n",
        "pkg/hub/factorytest/mock_github.go": 'mux.HandleFunc("/repos", fake)\n',
        "pkg/hub/testhelpers.go": 'srv.HandleFunc("/", fake)\n',
        "pkg/hub/server_test.go": 'mux.HandleFunc("/x", h)\n',
    })
    assert rf.find_route_files(repo) == ["cmd/bridge/main.go", "pkg/hub/server.go"]


def test_go_route_discovery_keeps_ordinary_names_that_contain_test(tmp_path):
    """`latest.go`, `attestation.go` and `testimonials.go` are ordinary names;
    only a file named like test scaffolding (`*_test.go`, `testhelpers.go`,
    `testutil.go`, `testing.go`) is left out."""
    repo = _repo(tmp_path / "repo", {
        "pkg/api/latest.go": 'mux.HandleFunc("/v/latest", h)\n',
        "pkg/api/attestation.go": 'mux.HandleFunc("/attest", h)\n',
        "pkg/api/testimonials.go": 'mux.HandleFunc("/testimonials", h)\n',
        "pkg/api/testhelpers.go": 'srv.HandleFunc("/", fake)\n',
        "pkg/api/testutil.go": 'srv.HandleFunc("/", fake)\n',
        "pkg/api/testing.go": 'srv.HandleFunc("/", fake)\n',
    })
    assert rf.find_route_files(repo) == ["pkg/api/attestation.go", "pkg/api/latest.go", "pkg/api/testimonials.go"]


def test_a_large_name_matched_manifest_is_still_read(tmp_path):
    """The per-file cap protects the Go content scan, which reads every
    candidate; a manifest found by name is read whatever its size, as it was
    before the scan existed."""
    from crawl.core import DEFAULT_MAX_FILE_BYTES
    big = "type Query {\n" + "  f: Int\n" * (DEFAULT_MAX_FILE_BYTES // 8) + "}\n"
    repo = _repo(tmp_path / "repo", {"api/schema.graphql": big})
    routes, files, kept = rf.crawl_routes(repo)
    assert kept == ["api/schema.graphql"] and "type Query" in routes
    assert rf.read_files(repo, ["api/schema.graphql"])[1] == ["api/schema.graphql"]


def test_a_typed_client_does_not_outrank_a_real_router(tmp_path):
    """Five path-literal calls alone do not make a manifest; a manifest also
    builds a mux or router, which a client wrapper does not."""
    repo = _repo(tmp_path / "repo", {
        "pkg/github/client.go": "".join(f'c.Get("/repos/{i}", &out)\n' for i in range(6)),
        "pkg/server/server.go": "m := http.NewServeMux()\n" + "".join(f'm.HandleFunc("/a/{i}", h)\n' for i in range(4)),
    })
    routes, files, kept = rf.crawl_routes(repo)
    assert files[0] == "pkg/server/server.go"


def test_a_serving_cmd_main_is_the_surface_when_no_go_file_registers_anything(tmp_path):
    """A Go server whose registrations take a form the heuristic does not know
    (paths in constants, a code-generated router) must not leave the surface
    empty; the cmd/*/main.go that starts the listener stands in, unweighted.
    A CLI's main.go, which starts none, does not."""
    repo = _repo(tmp_path / "repo", {
        "cmd/server/main.go": "func main() { s := newServer(); s.Run() }\n",
        "internal/api/routes.go": "r.Get(usersPath, list)\n",
        "cmd/tool/main.go": "func main() { cmd.Execute() }\n",
    })
    assert rf.find_route_files(repo) == ["cmd/server/main.go"]


def test_go_route_discovery_leaves_an_oversized_file_unread(tmp_path):
    """The walk reads every candidate .go file's text; a generated file over
    the shared per-file cap is skipped whole rather than read to run a regex."""
    from crawl.core import DEFAULT_MAX_FILE_BYTES
    big = 'mux.HandleFunc("/x", h)\n' + "x" * DEFAULT_MAX_FILE_BYTES
    repo = _repo(tmp_path / "repo", {"pkg/gen/zz_generated.go": big, "pkg/api/server.go": 'mux.HandleFunc("/y", h)\n'})
    assert rf.find_route_files(repo) == ["pkg/api/server.go"]


def test_crawl_routes_refuses_a_go_file_symlinked_out_of_the_repo(tmp_path):
    """The Go content path is a third read path in this module, and this seam
    has been missed here twice (coderay-q2r.28, q2r.56). A symlink out of the
    repo is not read, so it registers nothing and is not on the surface."""
    outside = tmp_path / "outside.go"
    outside.write_text('mux.HandleFunc("/leak", h)\nOUTSIDE-SECRET-CONTENT\n', encoding="utf-8")
    repo = _repo(tmp_path / "repo", {"config/routes.rb": "Rails.routes\n"})
    os.makedirs(os.path.join(repo, "pkg"), exist_ok=True)
    os.symlink(outside, os.path.join(repo, "pkg", "server.go"))
    routes, files, kept = rf.crawl_routes(repo)
    assert "OUTSIDE-SECRET-CONTENT" not in routes
    assert kept == ["config/routes.rb"] and files == kept


def test_name_matched_manifests_come_before_go_manifests_which_come_busiest_first(tmp_path):
    """A route-file name is certain; the registration count is a heuristic. So
    a Django manifest is read first, then Go manifests busiest first, then
    single handlers in name order whatever their language."""
    repo = _repo(tmp_path / "repo", {
        "zzz/urls.py": "urlpatterns = []\n",
        "aaa/five.go": "".join(f'mux.HandleFunc("/a/{i}", h)\n' for i in range(5)),
        "mmm/eight.go": "".join(f'mux.HandleFunc("/m/{i}", h)\n' for i in range(8)),
        "pages/api/aaa.ts": "export default aaa\n",
        "cmd/bridge/main.go": "m := http.NewServeMux()\n",
    })
    routes, files, kept = rf.crawl_routes(repo)
    assert files == ["zzz/urls.py", "mmm/eight.go", "aaa/five.go", "cmd/bridge/main.go", "pages/api/aaa.ts"]
    assert sorted(files) == rf.find_route_files(repo)


def test_find_route_files_skips_non_go_fixtures_too(tmp_path):
    repo = _repo(tmp_path / "repo", {"app/urls.py": "x\n", "testdata/routes.ts": "x\n", "app/testutil/urls.py": "x\n"})
    assert rf.find_route_files(repo) == ["app/urls.py"]


def test_read_files_does_not_resolve_a_bare_name_into_a_fixture_directory(tmp_path):
    """The suffix index comes from the same walk, so a model-named `users.py`
    that exists only under testdata/ is not read; an exact path still is."""
    repo = _repo(tmp_path / "repo", {"testdata/users.py": "FIXTURE\n", "api/a.py": "x\n"})
    assert rf.read_files(repo, ["users.py"])[1] == []
    assert rf.read_files(repo, ["testdata/users.py"])[1] == ["testdata/users.py"]


def test_go_manifest_threshold_boundary(tmp_path):
    """Five registrations make a manifest that sorts ahead of single handlers;
    four do not."""
    def repo_with(n):
        return _repo(tmp_path / f"r{n}", {
            "pkg/hub/server.go": "".join(f'mux.HandleFunc("/api/{i}", h)\n' for i in range(n)),
            "pages/api/aaa.ts": "export default aaa\n",
        })
    assert rf.crawl_routes(repo_with(5))[1][0] == "pkg/hub/server.go"
    assert rf.crawl_routes(repo_with(4))[1][0] == "pages/api/aaa.ts"


def test_crawl_routes_puts_the_go_file_with_the_most_registrations_first(tmp_path):
    """Six registrations make a manifest; a two-line mux in an entry point does
    not. The manifest is read first, so a cap would trim the entry point."""
    repo = _repo(tmp_path / "repo", {
        "cmd/bridge/main.go": "m := http.NewServeMux()\nm.Handle(path, h)\n",
        "pkg/hub/server.go": "".join(f'mux.HandleFunc("/api/{i}", h{i})\n' for i in range(6)),
        "pages/api/aaa.ts": "export default aaa\n",
    })
    routes, files, kept = rf.crawl_routes(repo)
    assert routes.index("pkg/hub/server.go") < min(routes.index("pages/api/aaa.ts"), routes.index("cmd/bridge/main.go"))
    assert files[0] == "pkg/hub/server.go"
