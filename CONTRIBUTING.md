# Contributing

## Setup

```bash
make install       # uv sync --locked
cp .env.example .env
```

Add one API key to `.env`. See `.env.example` for the full list of keys. You need a key only to run the pipeline against a real repo (`crack tour path/to/repo`). The test suite needs no key. The test suite needs no network access.

## Running tests

```bash
make test          # uv run pytest tests/ -q
```

The tests fake LLM (large language model) calls at the `call_llm`/`yaml_call` boundary. See `tests/conftest.py`. The tests do not mock code deeper in the call stack. CI (continuous integration) runs the same test suite on every push and pull request. See `.github/workflows/tests.yml`.

## Making a change

This codebase follows a few conventions. See `CLAUDE.md` for the full list.

- Parse LLM YAML output through `crack.core.yaml_call`. This function retries with a varied prompt when it gets a bad response. Do not add a new parse-and-retry loop in `src/crack/analyses/tour/nodes.py`.
- Escape untrusted input before it reaches HTML or Mermaid output. Untrusted input includes the target repo's own files. It also includes anything the LLM echoes back from those files. `src/crack/analyses/tour/render.py` once had a confirmed stored-XSS (cross-site scripting) bug here. Read `.full-review/02a-security.md` before you change that file's rendering code.
- Enforce a file-content budget (`preview_budget`, `codebase_budget`) by capping how many files the pipeline includes. Do not enforce the budget by raising a per-file floor instead. The per-file-floor approach caused two scalability bugs in the past.
- Add a new output lens by adding one file to `src/crack/analyses/tour/instructions/`. This step needs no code change and no registration step.

This project has no linter and no formatter configured. Match the style of the surrounding code.

## Pull requests

Keep test output clean. When a test triggers an error on purpose, assert on that error's output. Do not let the error print unchecked. Open your pull request against the `main` branch. CI must pass before a merge.

## Full architecture writeup

`README.md` covers the pipeline and the CLI (command-line interface) from a user's point of view. `.full-review/*.md` holds a full code review of the whole codebase. The fixes from that review are already on `main`. Read the review before you make a non-trivial change.
