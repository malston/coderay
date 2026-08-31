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
