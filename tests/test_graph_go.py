"""coderay-d5f. Go import resolution is package-level: an import path names a
directory, and the edge goes to every selected .go file in it. The repo's own
packages are the paths under the module path in go.mod at the repo root."""
import pytest

from crawl.analyses.tour.graph.languages.go import imports, module_path


@pytest.fixture
def root(tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/acme/app\n\ngo 1.25\n", encoding="utf-8")
    return str(tmp_path)


def test_imports_resolves_a_module_path_to_every_selected_file_in_the_package_dir(root):
    """Test files are never linked into the imported package, so they are not
    targets; a _test.go importer still gets its own edges."""
    text = 'package hub\n\nimport (\n\t"fmt"\n\t"github.com/acme/app/pkg/types"\n)\n'
    selected = {"pkg/hub/server.go", "pkg/types/a.go", "pkg/types/b.go", "pkg/types/c_test.go"}
    assert imports("pkg/hub/server.go", text, selected, root) == ["pkg/types/a.go", "pkg/types/b.go"]
    assert imports("pkg/hub/server_test.go", text, selected, root) == ["pkg/types/a.go", "pkg/types/b.go"]


def test_imports_drops_standard_library_and_third_party_paths(root):
    """Paths outside the module are not this repo's packages, even when a
    directory here happens to share their last segment."""
    text = 'package main\n\nimport (\n\t"fmt"\n\t"net/http"\n\t"github.com/spf13/cobra"\n)\n'
    selected = {"main.go", "fmt/x.go", "cobra/y.go"}
    assert imports("main.go", text, selected, root) == []


def test_imports_handles_a_single_import_and_an_aliased_one(root):
    text = 'package main\n\nimport "github.com/acme/app/internal/db"\nimport t "github.com/acme/app/pkg/types"\n'
    selected = {"main.go", "internal/db/db.go", "pkg/types/a.go"}
    assert imports("main.go", text, selected, root) == ["internal/db/db.go", "pkg/types/a.go"]


def test_imports_resolves_the_module_root_package(root):
    text = 'package x\n\nimport "github.com/acme/app"\n'
    selected = {"cmd/x/x.go", "main.go", "app.go"}
    assert imports("cmd/x/x.go", text, selected, root) == ["app.go", "main.go"]


def test_imports_never_points_a_file_at_its_own_package(root):
    text = 'package types\n\nimport "github.com/acme/app/pkg/types"\n'
    selected = {"pkg/types/a.go", "pkg/types/b.go"}
    assert imports("pkg/types/a.go", text, selected, root) == []


def test_imports_drops_a_package_with_no_selected_files(root):
    text = 'package x\n\nimport "github.com/acme/app/pkg/unpicked"\n'
    assert imports("x.go", text, {"x.go"}, root) == []


def test_imports_extracts_nothing_without_a_go_mod_and_says_so_once(tmp_path, capsys):
    """No module path means module and third-party paths are indistinguishable;
    better no edges than guessed ones. A missing go.mod (a monorepo with
    backend/go.mod, say) gets the same single note as one without a module line."""
    text = 'package x\n\nimport "github.com/acme/app/pkg/types"\n'
    for f in ("x.go", "y.go"):
        assert imports(f, text, {"x.go", "y.go", "pkg/types/a.go"}, str(tmp_path)) == []
    assert imports("x.go", text, {"x.go", "pkg/types/a.go"}) == []
    assert module_path(None) is None
    assert capsys.readouterr().out.count("no go.mod or module path") == 1


def test_module_path_follows_a_changed_go_mod(tmp_path):
    """Read once per root while go.mod is unchanged; a rewritten go.mod is read
    again, so a long-lived process or a second run does not see a stale path."""
    (tmp_path / "go.mod").write_text("module github.com/acme/one\n", encoding="utf-8")
    assert module_path(str(tmp_path)) == "github.com/acme/one"
    import os, time
    (tmp_path / "go.mod").write_text("module github.com/acme/two\n", encoding="utf-8")
    os.utime(tmp_path / "go.mod", ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert module_path(str(tmp_path)) == "github.com/acme/two"


def test_imports_returns_empty_for_a_file_with_no_imports(root):
    assert imports("main.go", "package main\n\nfunc main() {}\n", {"main.go"}, root) == []


def test_module_path_accepts_every_legal_module_line_shape(tmp_path):
    """A trailing comment, a quoted path, and the factored block form are all
    legal go.mod; each must yield the path, or the repo silently gets zero Go
    edges behind a coverage line that reads as full."""
    for text, want in (("module github.com/acme/app // v2 note\n", "github.com/acme/app"),
                       ('module "github.com/acme/app"\n', "github.com/acme/app"),
                       ("// module github.com/old\nmodule github.com/new\n", "github.com/new"),
                       ("module (\n\tgithub.com/acme/app\n)\n\ngo 1.25\n", "github.com/acme/app"),
                       ("module (\n\t// the one true path\n\tgithub.com/acme/app\n)\n", "github.com/acme/app"),
                       ("go 1.25\n", None)):
        d = tmp_path / str(abs(hash(text))); d.mkdir()
        (d / "go.mod").write_text(text, encoding="utf-8")
        assert module_path(str(d)) == want, text


def test_module_path_survives_a_go_mod_that_is_not_utf8(tmp_path):
    (tmp_path / "go.mod").write_bytes(b"module github.com/acme/app\n\xff\xfe\n")
    assert module_path(str(tmp_path)) == "github.com/acme/app"


def test_imports_resolves_a_raw_string_import_path(root):
    text = 'package x\n\nimport `github.com/acme/app/pkg/types`\n'
    assert imports("x.go", text, {"x.go", "pkg/types/a.go"}, root) == ["pkg/types/a.go"]


def test_imports_requires_the_module_prefix_to_end_at_a_segment(root):
    """`github.com/acme/appx/...` shares a string prefix with the module and is
    not in it."""
    text = 'package x\n\nimport "github.com/acme/appx/pkg"\n'
    assert imports("x.go", text, {"x.go", "pkg/p.go"}, root) == []


def test_imports_resolves_under_a_module_path_with_a_major_version_suffix(tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/acme/app/v2\n", encoding="utf-8")
    text = 'package x\n\nimport "github.com/acme/app/v2/pkg/types"\n'
    assert imports("x.go", text, {"x.go", "pkg/types/a.go"}, str(tmp_path)) == ["pkg/types/a.go"]


def test_imports_handles_blank_dot_and_duplicate_aliased_imports(root):
    text = ('package x\n\nimport (\n\t_ "github.com/acme/app/pkg/a"\n\t. "github.com/acme/app/pkg/b"\n'
            '\tc1 "github.com/acme/app/pkg/c"\n\tc2 "github.com/acme/app/pkg/c"\n)\n')
    selected = {"x.go", "pkg/a/a.go", "pkg/b/b.go", "pkg/c/c.go"}
    assert imports("x.go", text, selected, root) == ["pkg/a/a.go", "pkg/b/b.go", "pkg/c/c.go"]


def test_imports_yields_only_go_files_from_the_package_directory(root):
    text = 'package x\n\nimport "github.com/acme/app/pkg/types"\n'
    selected = {"x.go", "pkg/types/a.go", "pkg/types/README.md", "pkg/types/schema.sql"}
    assert imports("x.go", text, selected, root) == ["pkg/types/a.go"]


def test_a_repo_without_a_module_path_says_so_once(tmp_path, capsys):
    """The coverage line counts a Go file as covered when the extractor returns,
    so without this note a repo with no usable go.mod reads as fully covered
    with zero edges behind it."""
    (tmp_path / "go.mod").write_text("go 1.25\n", encoding="utf-8")
    for f in ("a.go", "b.go"):
        imports(f, 'package x\n\nimport "github.com/acme/app/pkg"\n', {"a.go", "b.go", "pkg/p.go"}, str(tmp_path))
    out = capsys.readouterr().out
    assert out.count("no go.mod or module path") == 1
