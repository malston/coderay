"""Architecture nodes: map a multi-service architecture in three passes.

  1. BuildBundle   assemble the architecture bundle from the four sources
  2. Inventory     name every node, sort into 4 bands, draw the service graph
  3. TechStack     open each box: the specific tech it's built from
  4. TraceRequest  trace the core action hop by hop, plus its variants

Inventory runs first; its numbered node list (stable IDs) is reused by TechStack
and TraceRequest so all three passes talk about the same graph.
"""
import re
from importlib import resources

from pocketflow import Node

from crawl.core import call_llm, read_prompt, fill, extract_mermaid
from . import arch_crawl as ac

PROMPTS_DIR = resources.files("crawl.analyses.architecture") / "prompts"


def load_prompt(name):
    return read_prompt(PROMPTS_DIR, name)


class BuildBundle(Node):
    def prep(self, shared):
        return shared["repo_path"]

    def exec(self, repo):
        return ac.build_bundle(repo)

    def post(self, shared, prep_res, exec_res):
        bundle, stats = exec_res
        reason = stats.get("sdk_unavailable")
        if not bundle.strip():
            # SystemExit, not assert: python -O strips asserts (coderay-q2r.50).
            raise SystemExit(
            "No architecture sources found (no compose/env/package/IaC). "
            + (f"SDK import evidence was also unavailable: {reason}. " if reason else "")
            + "This analysis expects a multi-service app; a single-binary tool "
            "has no service graph to draw.")
        shared["codebase"] = bundle
        shared["arch_stats"] = stats
        shared["bundle_files"] = stats["files"]
        print(f"  Bundle: {stats['config_files']} config files, {stats['env_vars']} env vars, "
              f"{stats['deps']} deps, {stats['integrations']} integrations, {stats['sdk_lines']} SDK imports"
              + (f" (SDK imports unavailable: {stats['sdk_unavailable']})" if stats.get("sdk_unavailable") else ""))


class Inventory(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("inventory.md"), codebase=shared["codebase"])

    def exec(self, prompt):
        md = call_llm(prompt).strip()
        assert "###" in md, "inventory produced no `### N · node` cards"
        return md

    def post(self, shared, prep_res, exec_res):
        md = exec_res
        verdict = re.search(r"\*\*Shape verdict:\*\*\s*(.+)", md)
        shared["inventory_md"] = md
        shared["arch_diagram"] = extract_mermaid(md)
        shared["shape_verdict"] = verdict.group(1).strip() if verdict else ""
        n_nodes = len(re.findall(r'^###\s', md, re.MULTILINE))
        print(f"  Inventory: {n_nodes} nodes"
              + (" (graph drawn)" if shared["arch_diagram"] else " (no graph parsed)"))


class TechStack(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("tech-stack.md"),
                    codebase=shared["codebase"], inventory=shared["inventory_md"])

    def exec(self, prompt):
        md = call_llm(prompt).strip()
        assert "###" in md, "tech-stack produced no `### N · node` cards"
        return md

    def post(self, shared, prep_res, exec_res):
        shared["techstack_md"] = exec_res
        print(f"  Tech stack: {exec_res.count(chr(35) + '##')} nodes documented")


class TraceRequest(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("trace-request.md"),
                    codebase=shared["codebase"], inventory=shared["inventory_md"])

    def exec(self, prompt):
        md = call_llm(prompt).strip()
        assert "###" in md, "trace produced no `###` cards"
        return md

    def post(self, shared, prep_res, exec_res):
        shared["trace_md"] = exec_res
        print(f"  Trace: {exec_res.count(chr(35) + '##')} cards (trace + variants)")
