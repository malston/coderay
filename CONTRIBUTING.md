# Contributing

## Setup

```bash
make install       # uv sync --locked
cp .env.example .env
```

Fill in one API key in `.env` (see `.env.example` for the full list of options). You only need a key to run the pipeline against a real repo (`python -m workflow path/to/repo`); the test suite needs neither a key nor network access.

## Running tests

```bash
make test          # uv run pytest tests/ -q
```

LLM calls are faked at the `call_llm`/`yaml_call` boundary (see `tests/conftest.py`), not mocked deeper in the call stack. CI (`.github/workflows/tests.yml`) runs the same suite on every push and pull request.

## Making a change

A few conventions this codebase leans on -- see `CLAUDE.md` for the full list:

- LLM YAML parsing goes through `coderay_utils.yaml_call`, which retries with a varied prompt on a bad response. Don't reintroduce a local parse-and-retry loop in `workflow/nodes.py`.
- Untrusted input -- the target repo's own files, and anything the LLM echoes back from them -- must be escaped before it reaches HTML or Mermaid output. `workflow/__main__.py` had a confirmed stored-XSS bug here; see `.full-review/02a-security.md` before touching its rendering code.
- A file-content budget (`preview_budget`, `codebase_budget`) is enforced by capping how many files get included, never by raising a per-file floor. The inverse caused two scalability bugs previously.
- Adding a new output lens is just adding a file to `workflow/instructions/` -- no code change or registration step needed.

There's no linter or formatter configured for this project; match the style of the surrounding code.

## Pull requests

Keep test output clean -- if a test intentionally triggers an error, assert on that error's output rather than letting it print unchecked. Open a PR against `main`; CI must pass before merge.

## Full architecture writeup

`README.md` covers the pipeline and CLI from a user's point of view. `.full-review/*.md` is a comprehensive code review of the whole codebase (the fixes it found are already on `main`) and is worth reading before a non-trivial change.
