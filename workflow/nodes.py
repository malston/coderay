"""Codebase Knowledge Builder nodes.

Five steps from the book chapter:
  1. SmartCrawl    walk repo, then ask the LLM which files matter
  2. Analyze       extract 5-10 core abstractions as YAML
  3. Relate        map abstractions to each other as YAML edges
  4. WriteChapters one chapter per abstraction, with SEQUENTIAL CONTEXT
  5. (rendering happens in main.py)

Notes on reliability:
  - LLM calling nodes use Node(max_retries=3, wait=2). No try/except around call_llm.
  - YAML parsing is strict. Bad output triggers a retry via the node's retry plumbing.
  - File reads in the main path raise. The only swallowed errors are per file decode
    errors inside crawl(), which is correct: we don't want one binary blob to kill a
    walk over 10,000 files.
"""
import os, re, sys
from pocketflow import Node, BatchNode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import call_llm, list_files, safe_read, yaml_call  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(__file__))
PROMPTS_DIR = os.path.join(ROOT, 'prompts')
INSTRUCTIONS_DIR = os.path.join(ROOT, 'instructions')

PREVIEW_CHARS_PER_FILE = 800
CODEBASE_BUDGET = 1_000_000
CHAPTER_CONTEXT_WINDOW = 3


def load_prompt(name):
    return open(os.path.join(PROMPTS_DIR, name)).read()


def load_instructions(name):
    return open(os.path.join(INSTRUCTIONS_DIR, f"{name}.md")).read()


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


# Step 1. Smart crawl: pick the files that matter
class SmartCrawl(Node):
    """First filter by extension and size (§3.2 prune the obvious),
    then ask the LLM to pick the ~0.1-2% of files that capture the architecture."""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        root = shared["repo_path"]
        all_files = list_files(root)
        budget = shared.get("preview_budget", 1_000_000)
        chars_per_file = PREVIEW_CHARS_PER_FILE
        max_files = max(1, budget // chars_per_file)
        files = all_files[:max_files]
        target = shared.get("target_files", min(50, max(20, len(files) // 20)))

        manifest_parts = []
        for i, path in enumerate(files):
            preview = safe_read(path, max_chars=chars_per_file) or ""
            rel = os.path.relpath(path, root)
            manifest_parts.append(f"  [{i}] {rel}\n{preview}\n")
        manifest = "\n".join(manifest_parts)

        prompt = load_prompt("select-files.md").format(
            manifest=manifest,
            chars_per_file=chars_per_file,
            target_count=target,
        )
        return prompt, files, root

    def exec(self, inputs):
        prompt, files, root = inputs

        def normalize(result):
            indices = result["selected"]
            assert all(0 <= i < len(files) for i in indices), \
                f"LLM returned out of range indices: {indices}"
            return [files[i] for i in indices], result.get("reasoning", "")

        return yaml_call(prompt, normalize)

    def post(self, shared, prep_res, exec_res):
        selected, reasoning = exec_res
        root = shared["repo_path"]
        budget = shared.get("codebase_budget", CODEBASE_BUDGET)
        parts = []
        included = []
        total_chars = 0
        for p in selected:
            if total_chars >= budget:
                break
            text = safe_read(p)
            if text is None:
                continue
            block = f"{'=' * 60}\nFile: {os.path.relpath(p, root)}\n{'=' * 60}\n{text}"
            parts.append(block)
            included.append(p)
            total_chars += len(block)
        shared["codebase"] = "\n\n".join(parts)
        shared["selected_files"] = [os.path.relpath(p, root) for p in included]
        shared["selection_reasoning"] = reasoning
        dropped = len(selected) - len(included)
        if dropped:
            print(f"  Dropped {dropped} files over codebase budget ({budget:,} chars)")
        print(f"  Selected {len(included)} files ({len(shared['codebase']):,} chars)")


# Step 2. Identify the abstractions
class Analyze(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return load_prompt("identify-abstractions.md").format(codebase=shared["codebase"])

    def exec(self, prompt):
        def normalize(result):
            names = [a["name"] for a in result["abstractions"]]
            order = result["learning_order"]
            assert len(names) == len(set(names)), f"duplicate abstraction names: {names}"
            assert sorted(names) == sorted(order), \
                f"abstractions and learning_order disagree: {set(names) ^ set(order)}"
            return result

        return yaml_call(prompt, normalize)

    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res["summary"]
        shared["abstractions"] = exec_res["abstractions"]
        shared["order"] = exec_res["learning_order"]
        print(f"  Found {len(exec_res['abstractions'])} abstractions")


# Step 3. Map relationships
class Relate(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        listing = "\n".join(
            f"- {a['name']}: {a['description'].strip()}" for a in shared["abstractions"]
        )
        return load_prompt("analyze-relationships.md").format(
            abstractions=listing, codebase=shared["codebase"]
        )

    def exec(self, prompt):
        return yaml_call(prompt, lambda result: result["relationships"])

    def post(self, shared, prep_res, exec_res):
        shared["relationships"] = exec_res
        print(f"  Found {len(exec_res)} relationships")


# Step 4. Write chapters SEQUENTIALLY, passing prior chapters as context
class WriteChapters(Node):
    """NOT a BatchNode. Each chapter needs the previous chapters as context so the
    tutorial reads as a narrative, not a pile of disconnected pages (§3.3)."""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        by_name = {a["name"]: a for a in shared["abstractions"]}
        order = shared["order"]
        filenames = {n: f"{i+1:02d}_{slug(n)}.md" for i, n in enumerate(order)}
        chapter_list = "\n".join(f"- [{n}]({filenames[n]})" for n in order)
        instructions = load_instructions(shared.get("instructions", "beginner-tutorial"))
        return {
            "by_name": by_name,
            "order": order,
            "filenames": filenames,
            "chapter_list": chapter_list,
            "codebase": shared["codebase"],
            "instructions": instructions,
            "context_window": shared.get("chapter_context_window", CHAPTER_CONTEXT_WINDOW),
        }

    def exec(self, ctx):
        chapters = []
        prev_chapters = []
        total = len(ctx["order"])
        window = ctx["context_window"]
        for i, name in enumerate(ctx["order"]):
            print(f"  Chapter {i+1}/{total}: {name}")
            recent = prev_chapters[-window:] if window else prev_chapters
            prev = "\n\n---\n\n".join(recent) if recent else "(This is the first chapter.)"
            prompt = load_prompt("write-chapter.md").format(
                name=name,
                description=ctx["by_name"][name]["description"],
                chapter_num=i + 1,
                total=total,
                prev_chapters=prev,
                chapter_list=ctx["chapter_list"],
                codebase=ctx["codebase"],
                instructions=ctx["instructions"],
            )
            content = call_llm(prompt)
            chapters.append({"name": name, "filename": ctx["filenames"][name], "content": content})
            prev_chapters.append(content)
        return chapters

    def post(self, shared, prep_res, exec_res):
        shared["chapters"] = exec_res
        shared["filenames"] = prep_res["filenames"]
