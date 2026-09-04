"""Codebase Knowledge Builder nodes.

Five steps from the book chapter (plus a deterministic graph-extraction step):
  1. SmartCrawl    walk repo, then ask the LLM which files matter
  1.5 ExtractGraph parse selected files for a deterministic import graph
  2. Analyze       extract 5-10 core abstractions as YAML
  3. Relate        map abstractions to each other as YAML edges
  4. WriteChapters one chapter per abstraction, with SEQUENTIAL CONTEXT
  5. (rendering happens in crawl/analyses/tour/render.py)

Notes on reliability:
  - SmartCrawl, Analyze, and Relate parse a ```yaml reply through crawl.core.yaml_call,
    which already retries (with a varied prompt tail) on bad output, so their
    Node max_retries stays at 1 -- a second retry layer on top would multiply
    LLM calls for a genuinely bad reply without adding anything.
  - WriteChapters doesn't parse structured output, so it keeps Node(max_retries=3,
    wait=2) as its only retry layer, for transient call_llm failures. A
    truncated chapter is not transient and exits the run instead.
  - File reads in the main path raise. The only swallowed errors are per file decode
    errors inside crawl.core.safe_read(), which is correct: we don't want one binary blob
    to kill a walk over 10,000 files.
"""
import os
import re
from importlib import resources
from typing import TypedDict

from pocketflow import Node, BatchNode

from crawl.core import ResponseTruncated, call_llm, fill, list_files, read_prompt, safe_read, yaml_call
from crawl.analyses.tour.graph.languages import REGISTRY

PROMPTS_DIR = resources.files("crawl.analyses.tour") / "prompts"
INSTRUCTIONS_DIR = resources.files("crawl.analyses.tour") / "instructions"

PREVIEW_CHARS_PER_FILE = 800
CODEBASE_BUDGET = 1_000_000
CHAPTER_CONTEXT_WINDOW = 3


class PipelineState(TypedDict, total=False):
    """The dict threaded through create_tour_flow()'s nodes (SmartCrawl >>
    ExtractGraph >> Analyze >> Relate >> WriteChapters), and read afterward by
    crawl.analyses.tour.render's renderers. Not validated at runtime -- documents the contract each node's
    untyped `shared[...]` subscripts rely on. Every key past instructions is
    optional at the type level since it's only present once the node that
    writes it has run.

    Set by the caller before the flow runs:
      repo_path               str   directory to analyze
      instructions             str   instructions/<name>.md lens to use

    Optional overrides read via shared.get(...) (all have defaults):
      preview_budget           int   SmartCrawl.prep: char budget for the file preview manifest
      target_files             int   SmartCrawl.prep: target selected-file count
      codebase_budget          int   SmartCrawl.post: char budget for the assembled codebase
      chapter_context_window   int   WriteChapters.prep: # of prior chapters kept as context

    Written by SmartCrawl.post; read by Analyze/Relate/WriteChapters.prep and
    crawl.analyses.tour.render's renderers:
      codebase                 str
      selected_files           list[str]
      selection_reasoning      str

    Written by ExtractGraph.post; read by Relate.prep:
      symbol_graph            list[dict]

    Written by Analyze.post; read by Relate/WriteChapters.prep and
    crawl.analyses.tour.render's renderers:
      summary                  str
      abstractions             list[dict]  # each with "files": list[str]
      order                    list[str]

    Written by Relate.post; read by crawl.analyses.tour.render.build_mermaid:
      relationships            list[dict]  # each with "source": "EXTRACTED" | "INFERRED"

    Written by WriteChapters.post; read by crawl.analyses.tour.render's renderers:
      chapters                 list[dict]
      filenames                dict[str, str]
    """
    repo_path: str
    instructions: str
    preview_budget: int
    target_files: int
    codebase_budget: int
    chapter_context_window: int
    codebase: str
    selected_files: list
    selection_reasoning: str
    symbol_graph: list
    summary: str
    abstractions: list
    order: list
    relationships: list
    chapters: list
    filenames: dict


def load_instructions(name):
    return read_prompt(INSTRUCTIONS_DIR, f"{name}.md")


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


# Step 1. Smart crawl: pick the files that matter
class SmartCrawl(Node):
    """First filter by extension and size (prune the obvious),
    then ask the LLM to pick the ~0.1-2% of files that capture the architecture."""
    def __init__(self):
        super().__init__(max_retries=1)

    def prep(self, shared: PipelineState):
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

        prompt = fill(
            read_prompt(PROMPTS_DIR, "select-files.md"),
            manifest=manifest,
            chars_per_file=chars_per_file,
            target_count=target,
        )
        return prompt, files, root

    def exec(self, inputs):
        prompt, files, root = inputs

        def normalize(result):
            indices = result["selected"]
            if not all(0 <= i < len(files) for i in indices):
                raise ValueError(f"LLM returned out of range indices: {indices}")
            return [files[i] for i in indices], result.get("reasoning", "")

        return yaml_call(prompt, normalize)

    def post(self, shared: PipelineState, prep_res, exec_res):
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


# Step 1.5. Extract a deterministic import graph as ground truth for Relate
class ExtractGraph(Node):
    """Parses each selected file with a per-extension tree-sitter extractor
    (src/crawl/analyses/tour/graph/languages/) and records import edges that land inside
    selected_files. A file whose extension has no registered extractor
    produces no edges -- Relate falls back to LLM-INFERRED only for
    relationships that only touch it (imports-only, Python/JS/TS/Go; see
    docs/superpowers/specs/2026-08-31-deterministic-import-graph-design.md)."""
    def __init__(self):
        super().__init__(max_retries=1)

    def prep(self, shared: PipelineState):
        return shared["repo_path"], shared["selected_files"]

    def exec(self, inputs):
        root, selected = inputs
        selected_set = set(selected)
        edges = []
        covered = 0
        for rel_path in selected:
            extractor = REGISTRY.get(os.path.splitext(rel_path)[1].lower())
            if extractor is None:
                continue
            text = safe_read(os.path.join(root, rel_path))
            if text is None:
                continue
            try:
                targets = extractor.imports(rel_path, text, selected_set, root)
            except Exception as e:
                print(f"  Skipping {rel_path} for import graph: {e}")
                continue
            covered += 1
            for target in targets:
                edges.append({"from": rel_path, "to": target, "kind": "imports"})
        return edges, covered

    def post(self, shared: PipelineState, prep_res, exec_res):
        edges, covered = exec_res
        shared["symbol_graph"] = edges
        total = len(prep_res[1])
        print(f"  {covered}/{total} selected files covered by a deterministic import graph")


# Step 2. Identify the abstractions
class Analyze(Node):
    def __init__(self):
        super().__init__(max_retries=1)

    def prep(self, shared: PipelineState):
        selected = shared["selected_files"]
        files_list = "\n".join(f"- {f}" for f in selected)
        prompt = fill(
            read_prompt(PROMPTS_DIR, "identify-abstractions.md"),
            codebase=shared["codebase"], selected_files=files_list,
        )
        return prompt, set(selected)

    def exec(self, inputs):
        prompt, selected_files = inputs

        def normalize(result):
            abstractions = result["abstractions"]
            assert isinstance(abstractions, list) and all(isinstance(a, dict) for a in abstractions), \
                f"abstractions must be a list of objects: {abstractions!r}"
            names = [a["name"] for a in abstractions]
            order = result["learning_order"]
            assert len(names) == len(set(names)), f"duplicate abstraction names: {names}"
            assert sorted(names) == sorted(order), \
                f"abstractions and learning_order disagree: {set(names) ^ set(order)}"
            for a in abstractions:
                assert "files" in a, f"{a['name']!r} is missing required field 'files'"
                files = a["files"]
                assert isinstance(files, list) and all(isinstance(f, str) for f in files), \
                    f"{a['name']!r} files must be a list of strings: {files!r}"
                bad = [f for f in files if f not in selected_files]
                assert not bad, f"{a['name']!r} files not in selected_files: {bad}"
            return result

        return yaml_call(prompt, normalize)

    def post(self, shared: PipelineState, prep_res, exec_res):
        shared["summary"] = exec_res["summary"]
        shared["abstractions"] = exec_res["abstractions"]
        shared["order"] = exec_res["learning_order"]
        print(f"  Found {len(exec_res['abstractions'])} abstractions")


# Step 3. Map relationships
class Relate(Node):
    def __init__(self):
        super().__init__(max_retries=1)

    def prep(self, shared: PipelineState):
        listing = "\n".join(
            f"- {a['name']}: {a['description'].strip()}" for a in shared["abstractions"]
        )
        prompt = fill(
            read_prompt(PROMPTS_DIR, "analyze-relationships.md"),
            abstractions=listing, codebase=shared["codebase"],
        )
        return prompt, shared["abstractions"], shared.get("symbol_graph", [])

    def exec(self, inputs):
        prompt, abstractions, symbol_graph = inputs
        files_by_name = {a["name"]: set(a.get("files", [])) for a in abstractions}

        def normalize(result):
            relationships = result["relationships"]
            assert isinstance(relationships, list) and all(isinstance(r, dict) for r in relationships), \
                f"relationships must be a list of objects: {relationships!r}"
            for r in relationships:
                for field in ("from", "to", "label"):
                    assert isinstance(r.get(field), str) and r[field], \
                        f"relationship missing/invalid {field!r}: {r!r}"
                from_files = files_by_name.get(r["from"])
                to_files = files_by_name.get(r["to"])
                extracted = bool(from_files and to_files and any(
                    edge["kind"] == "imports" and edge["from"] in from_files and edge["to"] in to_files
                    for edge in symbol_graph
                ))
                r["source"] = "EXTRACTED" if extracted else "INFERRED"
            return relationships

        return yaml_call(prompt, normalize)

    def post(self, shared: PipelineState, prep_res, exec_res):
        shared["relationships"] = exec_res
        print(f"  Found {len(exec_res)} relationships")


# Step 4. Write chapters SEQUENTIALLY, passing prior chapters as context
class WriteChapters(Node):
    """NOT a BatchNode. Each chapter needs the previous chapters as context so the
    tour reads as a narrative, not a pile of disconnected pages."""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared: PipelineState):
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
            prompt = fill(
                read_prompt(PROMPTS_DIR, "write-chapter.md"),
                name=name,
                description=ctx["by_name"][name]["description"],
                chapter_num=i + 1,
                total=total,
                prev_chapters=prev,
                chapter_list=ctx["chapter_list"],
                codebase=ctx["codebase"],
                instructions=ctx["instructions"],
            )
            try:
                content = call_llm(prompt)
            except ResponseTruncated as e:
                # coderay-q2r.46: deterministic, so a retry would only rewrite
                # every earlier chapter again. SystemExit is not an Exception,
                # so it passes straight through the node's retry loop.
                raise SystemExit(f"Chapter {i+1}/{total} ({name}) overran the output cap: {e}") from e
            chapters.append({"name": name, "filename": ctx["filenames"][name], "content": content})
            prev_chapters.append(content)
        return chapters

    def post(self, shared: PipelineState, prep_res, exec_res):
        shared["chapters"] = exec_res
        shared["filenames"] = prep_res["filenames"]
