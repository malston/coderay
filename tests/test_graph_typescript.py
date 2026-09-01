import workflow.graph.languages.typescript as typescript_module
from workflow.graph.languages.typescript import imports


def test_imports_resolves_ts_relative_specifier():
    text = "import { helper } from './lib/helper';\n"
    selected = {"lib/helper.ts", "main.ts"}
    assert imports("main.ts", text, selected) == ["lib/helper.ts"]


def test_imports_resolves_tsx_relative_specifier():
    text = "import App from './App';\nconst el = <App />;\n"
    selected = {"App.tsx", "main.tsx"}
    assert imports("main.tsx", text, selected) == ["App.tsx"]


def test_imports_drops_bare_package_specifier():
    text = "import { z } from 'zod';\n"
    selected = {"main.ts"}
    assert imports("main.ts", text, selected) == []


def test_imports_drops_ambiguous_specifier_with_two_candidates():
    text = "import foo from './foo';\n"  # matches both foo.ts and foo.tsx -- ambiguous
    selected = {"foo.ts", "foo.tsx", "main.ts"}
    assert imports("main.ts", text, selected) == []


def test_imports_resolves_explicit_extension_specifier_even_with_decoy_file():
    # './x.ts' already names its extension -- an unrelated 'x.ts.tsx' file must
    # not make this look ambiguous and drop the edge.
    text = "import x from './x.ts';\n"
    selected = {"x.ts", "x.ts.tsx", "main.ts"}
    assert imports("main.ts", text, selected) == ["x.ts"]


def test_imports_resolves_index_file_with_platform_separator(monkeypatch):
    monkeypatch.setattr(typescript_module.os, "sep", "\\")
    text = "import lib from './lib';\n"
    selected = {"lib\\index.ts"}
    assert imports("main.ts", text, selected) == ["lib\\index.ts"]
