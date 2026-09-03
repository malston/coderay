"""Ch5 nodes: extract a product story from a codebase.

Four independent extractions (§5.1 to §5.4 of the chapter):
  - Pain scene (Curse of Knowledge)
  - Variant sentence (reproduce-it test)
  - Competitive positioning (counter-positioning)
  - Surprises and absences (Slack-and-Flickr signals)

Each is its own node with max_retries so bad LLM output retries cleanly.

The port source also has an IllustratePain node that asks Gemini for a
before/after cartoon and writes pain.png beside the report. It is not ported:
coderay ships this analysis text-only, so shared core needs no image provider
and the renderer's image slot stays empty (the port source already renders
cleanly without one).
"""
import os
from importlib import resources

from pocketflow import Node

from crack.core import call_llm, fill, list_files, read_prompt, safe_read, yaml_call

PROMPTS_DIR = resources.files("crack.analyses.product_intent") / "prompts"


def load_prompt(name):
    return read_prompt(PROMPTS_DIR, name)


def bundle(repo, include=None, exclude=None, max_chars=650_000):
    """Every kept file, whole, with a header, until the budget is spent.

    The port source concatenated the entire repo with no cap (coderay-q2r.47).
    The budget caps how many FILES go in, never how much of each: a file cut
    mid-way reads as a finished one to the model. Files come in list_files
    order, which already refuses symlinks that resolve outside the repo.
    """
    parts, total, included, dropped = [], 0, 0, 0
    for path in list_files(repo, include=include or None, exclude=exclude or None):
        text = safe_read(path)
        if text is None:
            continue
        rel = os.path.relpath(path, repo)
        block = f"{'=' * 60}\nFile: {rel}\n{'=' * 60}\n{text}\n"
        if total + len(block) + 1 > max_chars:
            dropped += 1
            continue
        parts.append(block)
        total += len(block) + 1
        included += 1
    return "\n".join(parts), {"included": included, "dropped": dropped}


class FetchRepo(Node):
    def prep(self, shared):
        return {
            "repo_path": shared["repo_path"],
            "include": shared.get("include") or None,
            "exclude": shared.get("exclude") or None,
        }

    def exec(self, ctx):
        return bundle(ctx["repo_path"], include=ctx["include"], exclude=ctx["exclude"])

    def post(self, shared, prep_res, exec_res):
        codebase, stats = exec_res
        assert codebase.strip(), (
            f"No source found under {prep_res['repo_path']} "
            f"(include={prep_res['include'] or 'all'}, exclude={prep_res['exclude'] or 'none'}). "
            "Nothing to read a product story from.")
        shared["codebase"] = codebase
        print(f"  Crawled {stats['included']} files ({len(codebase):,} chars) from {prep_res['repo_path']}")
        if stats["dropped"]:
            print(f"  Dropped {stats['dropped']} files over the codebase budget")


class PainScene(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("pain-scene.md"), codebase=shared["codebase"])

    def exec(self, prompt):
        return call_llm(prompt).strip()

    def post(self, shared, prep_res, exec_res):
        shared["pain"] = exec_res
        print(f"  Pain scene ({len(exec_res)} chars)")


class VariantSentence(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("variant-sentence.md"), codebase=shared["codebase"])

    def exec(self, prompt):
        return call_llm(prompt).strip()

    def post(self, shared, prep_res, exec_res):
        shared["variant"] = exec_res
        print(f"  Variant sentence: {exec_res[:80]}...")


class CompetitivePositioning(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("competitive-positioning.md"), codebase=shared["codebase"])

    def exec(self, prompt):
        def normalize(result):
            assert "competitors" in result and len(result["competitors"]) >= 2
            assert "dimensions" in result and len(result["dimensions"]) >= 3
            for k in ("sacrifices", "gains", "why_incumbents_cannot_copy"):
                assert k in result, f"missing {k} in positioning"
            # Each dimension must be {name, definition}: the renderer reads both,
            # so a bare string would pass validation and raise in render.py.
            for d in result["dimensions"]:
                assert isinstance(d, dict) and "name" in d and "definition" in d, \
                    f"dimension missing name/definition: {d!r}"
            for c in result["competitors"]:
                # coderay-q2r.48: the renderer reads c["name"] after the call is paid for.
                assert isinstance(c, dict) and "name" in c, f"competitor missing name: {c!r}"
                # Each cell must be {verdict, detail}. Reject the old flat-string shape so a retry kicks in.
                for cell in c.get("cells", []):
                    assert isinstance(cell, dict) and "verdict" in cell and "detail" in cell, \
                        f"cell missing verdict/detail in {c['name']}: {cell!r}"
            return result
        return yaml_call(prompt, normalize)

    def post(self, shared, prep_res, exec_res):
        shared["positioning"] = exec_res
        print(f"  Positioning: {len(exec_res['competitors'])} competitors, "
              f"{len(exec_res['dimensions'])} dimensions")


class SurprisesAndAbsences(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return fill(load_prompt("surprises-and-absences.md"), codebase=shared["codebase"])

    def exec(self, prompt):
        def normalize(result):
            assert "present" in result and "absent" in result
            for p in result["present"]:
                for k in ("headline", "where", "bet"):
                    assert k in p, f"present item missing {k}: {p!r}"
            for a in result["absent"]:
                for k in ("headline", "evidence", "tradeoff"):
                    assert k in a, f"absent item missing {k}: {a!r}"
            return result
        return yaml_call(prompt, normalize)

    def post(self, shared, prep_res, exec_res):
        shared["surprises"] = exec_res
        print(f"  Surprises: {len(exec_res['present'])} present, "
              f"{len(exec_res['absent'])} absent")
