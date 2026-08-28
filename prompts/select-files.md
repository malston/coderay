You are selecting the most important files from a codebase for understanding its core architecture.

Below is a file manifest. Each entry has an index, the file path, and the first ~{chars_per_file} characters (enough to see imports, class definitions, docstrings).

## Selection rules

1. **Start with entry points.** Files that bootstrap the application: `main.py`, `server.ts`, `app.py`, CLI commands. Their import list IS the architecture.

2. **Always pick a concrete implementation alongside every base class.** Reading only the base class teaches you the menu template. Reading one concrete model (say, BERT inside HuggingFace Transformers) teaches you what the menu actually serves.

3. **If you see N similar directories, pick ONE representative.** LangChain has 15 integration packages that follow the same shape. 77 messaging extensions in one chat platform. Read one, you know all of them.

4. **Skip plumbing, even when it has a meaningful name.** Telemetry, retry handlers, lock files, pre-commit configs, `.editorconfig`. These appear in every project and teach you nothing about *this* project.

Pick {target_count} files or fewer.

## File manifest

{manifest}

## Response

Respond in YAML, fenced. Reasoning FIRST so you commit to your logic before listing files:

```yaml
reasoning: |
  ONE paragraph, two to four sentences. What this codebase is, the main subsystems
  you see, and the rule of thumb you used to pick. Plain prose, no bullet lists,
  no numbered lists, no markdown.
selected:
  - 0    # path/to/file.py
  - 12   # path/to/other.py
```
