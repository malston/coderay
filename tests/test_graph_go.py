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
    text = 'package hub\n\nimport (\n\t"fmt"\n\t"github.com/acme/app/pkg/types"\n)\n'
    selected = {"pkg/hub/server.go", "pkg/types/a.go", "pkg/types/b.go", "pkg/types/c_test.go"}
    assert imports("pkg/hub/server.go", text, selected, root) == ["pkg/types/a.go", "pkg/types/b.go", "pkg/types/c_test.go"]


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


def test_imports_extracts_nothing_without_a_go_mod(tmp_path):
    """No module path means module and third-party paths are indistinguishable;
    better no edges than guessed ones."""
    text = 'package x\n\nimport "github.com/acme/app/pkg/types"\n'
    assert imports("x.go", text, {"x.go", "pkg/types/a.go"}, str(tmp_path)) == []
    assert imports("x.go", text, {"x.go", "pkg/types/a.go"}) == []
    assert module_path(str(tmp_path)) is None and module_path(None) is None


def test_imports_returns_empty_for_a_file_with_no_imports(root):
    assert imports("main.go", "package main\n\nfunc main() {}\n", {"main.go"}, root) == []
