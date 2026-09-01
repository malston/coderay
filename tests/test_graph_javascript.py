from workflow.graph.languages.javascript import imports


def test_imports_resolves_relative_specifier_with_extension_guess():
    text = "import { helper } from './lib/helper';\n"
    selected = {"lib/helper.js", "main.js"}
    assert imports("main.js", text, selected) == ["lib/helper.js"]


def test_imports_resolves_sibling_file_relative_to_importer_dir():
    text = "import x from './x';\n"
    selected = {"src/x.js", "src/main.js"}
    assert imports("src/main.js", text, selected) == ["src/x.js"]


def test_imports_drops_bare_package_specifier():
    text = "import React from 'react';\n"
    selected = {"main.js"}
    assert imports("main.js", text, selected) == []


def test_imports_handles_jsx_syntax():
    text = "import App from './App';\nconst el = <App />;\n"
    selected = {"App.jsx", "main.jsx"}
    assert imports("main.jsx", text, selected) == ["App.jsx"]


def test_imports_drops_ambiguous_specifier_with_two_candidates():
    text = "import foo from './foo';\n"  # matches both foo.js and foo.jsx -- ambiguous
    selected = {"foo.js", "foo.jsx", "main.js"}
    assert imports("main.js", text, selected) == []
