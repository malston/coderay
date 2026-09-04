"""Git-history nodes: read a product's story out of its git history.

Four steps, each a slice of the same commit list:
  1. FetchHistory  run the crawler; pull bulk additions/deletions once
  2. NameEras      compress 13 years into 3-5 named eras (bird's-eye)
  3. ProfileEras   for each era, the cast (who) and mood (what) — one era at a time
  4. Graveyard     read the code of the biggest deletions: the bets they killed

Reliability mirrors the rest of the repo: every LLM node uses
Node(max_retries=3, wait=2), JSON parsing is strict so bad output retries, and
gitlog's subprocess reads raise on any git failure rather than reporting no data.
"""
import os
import re
from importlib import resources

from pocketflow import Node

from crawl.core import call_llm, DEFAULT_SKIP_DIR, read_prompt, fill, json_call
from . import gitlog as gl

PROMPTS_DIR = resources.files("crawl.analyses.git_history") / "prompts"


def load_prompt(name):
    return read_prompt(PROMPTS_DIR, name)


def _is_noise_deletion(change):
    """True when a bulk deletion is vendored/build/test churn, not a killed feature.

    Removing `node_modules/` (thousands of files) or a `dist/` build dwarfs every
    real deletion by raw count, so ranking by size alone buries the actual graves.
    A deletion is noise when most of its files sit under a skip-list directory
    (the same set the crawler prunes: node_modules, vendor, dist, build, tests, …)."""
    files = change["files"]
    noisy = sum(1 for f in files if set(f.split(os.sep)) & DEFAULT_SKIP_DIR)
    return noisy > len(files) * 0.5


def _era_for(month, eras):
    """The era whose [start, end] window contains a YYYY-MM month (or None)."""
    for e in eras:
        if e["start"] <= month <= e.get("end", "9999-99"):
            return e
    return None  # coderay-q2r.40: not the last era, which mislabels a gap


# Step 1. Crawl the log; pull the bulk-change rosters once.
class FetchHistory(Node):
    def prep(self, shared):
        return shared["repo_path"]

    def exec(self, repo_path):
        commits = gl.git_log_commits(repo_path)
        return {
            "commits": commits,
            "commits_asc": gl.commits_ascending(commits),
            "bulk_adds": gl.bulk_changes(repo_path, "A", min_files=10),
            "bulk_dels": gl.bulk_changes(repo_path, "D", min_files=5),
            "shallow": gl.is_shallow(repo_path),
        }

    def post(self, shared, prep_res, exec_res):
        shared.update(exec_res)
        c = exec_res["commits"]
        span = f"{exec_res['commits_asc'][0]['month']}..{exec_res['commits_asc'][-1]['month']}" if c else "empty"
        print(f"  Crawled {len(c):,} commits ({span}), "
              f"{len(exec_res['bulk_adds'])} bulk adds, {len(exec_res['bulk_dels'])} bulk deletions")
        if exec_res["shallow"]:  # coderay-q2r.38
            print("  WARNING: this is a shallow clone; the log is a fragment of the "
                  "history and the eras will be wrong. Unshallow it first (git fetch --unshallow).")


_YEAR_MONTH = re.compile(r"\d{4}-\d{2}")


# Step 2. Name the eras from a bird's-eye survey.
class NameEras(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        commits = shared["commits"]
        big_dels = [c for c in shared["bulk_dels"] if c["count"] >= 10]
        return fill(
            load_prompt("name-eras.md"),
            heatmap_summary=gl.heatmap_summary(commits),
            pivots_summary=gl.pivots_summary(commits),
            deletions_summary=gl._changes_summary(big_dels) or "(none)",
            additions_summary=gl._changes_summary(shared["bulk_adds"]) or "(none)",
        )

    def exec(self, prompt):
        def normalize(result):
            if isinstance(result, dict):
                result = result.get("eras", [result])
            assert isinstance(result, list) and result, "expected a non-empty list of eras"
            for e in result:
                for k in ("name", "start", "end", "description", "turning_point"):
                    assert k in e, f"era missing {k!r}: {e!r}"
                # coderay-q2r.39: era windows are YYYY-MM string comparisons;
                # any other form selects no commits or raises outside the retry.
                for k in ("start", "end"):
                    assert isinstance(e[k], str) and _YEAR_MONTH.fullmatch(e[k]), \
                        f"era {k!r} must be YYYY-MM, got {e[k]!r}: {e!r}"
            return result
        return json_call(prompt, normalize)

    def post(self, shared, prep_res, exec_res):
        shared["eras"] = exec_res
        print(f"  Named {len(exec_res)} eras: " + " -> ".join(e["name"] for e in exec_res))


# Step 3. Profile each era's cast and mood, one era at a time.
class ProfileEras(Node):
    """A plain Node, not a BatchNode: each era's prompt carries the previous
    eras' summaries for cross-era contrast, so they run in sequence."""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        return {
            "repo_path": shared["repo_path"],
            "commits_asc": shared["commits_asc"],
            "eras": shared["eras"],
            "max_commits": shared.get("profile_max_commits", 400),
            "diff_chars": shared.get("profile_diff_chars", 2500),
            "template": load_prompt("profile-era.md"),
        }

    def exec(self, ctx):
        eras, template = ctx["eras"], ctx["template"]
        profiles, prior_lines = [], []
        for i, era in enumerate(eras):
            print(f"  Profiling era {i+1}/{len(eras)}: {era['name']}")
            window = gl.era_commits(ctx["commits_asc"], era["start"], era["end"])
            if not window:  # coderay-q2r.39
                print(f"  Era {era['name']!r} ({era['start']}..{era['end']}) matches no "
                      "commits; skipping its profile rather than asking the model to invent one")
                continue
            marks = gl.landmarks(window)
            sampled, was_sampled = gl.sample_commits(window, ctx["max_commits"])
            stream = gl.commit_stream(sampled)
            if was_sampled:
                stream = (f"(showing {len(sampled)} of {len(window)} commits, evenly sampled "
                          f"across the era)\n" + stream)
            diffs = {label: c for label, c in marks}
            slot = {}
            for label in ("opening", "early", "mid", "late", "closing"):
                c = diffs.get(label)
                slot[f"{label}_hash"] = c["hash"][:7] if c else ""
                slot[f"{label}_date"] = c["month"] if c else ""
                slot[f"{label}_subject"] = c["subject"] if c else ""
                slot[f"{label}_diff"] = (
                    gl.show_diff(ctx["repo_path"], c["hash"], max_chars=ctx["diff_chars"])
                    if c else "(no commit)"
                )
            prompt = fill(
                template,
                era_index=i + 1, total_eras=len(eras), era_name=era["name"],
                era_start=era["start"], era_end=era["end"],
                era_description=era["description"],
                prior_summaries="\n".join(prior_lines) or "(this is the first era)",
                commit_stream=stream or "(no commits)",
                **slot,
            )
            def normalize(result):
                if isinstance(result, dict) and "profile" in result:
                    result = result["profile"]  # some models wrap it
                assert isinstance(result, dict) and "cast" in result and "mood" in result, \
                    f"profile must be a JSON object with top-level `cast` and `mood`. Got keys: " \
                    f"{list(result) if isinstance(result, dict) else type(result).__name__}"
                # coderay-q2r.39: key presence is not shape; a string here
                # failed at .get() outside json_call and re-ran every era.
                assert isinstance(result["cast"], dict) and "contributors" in result["cast"], \
                    f"`cast` must be an object with `contributors`, got {result['cast']!r}"
                assert isinstance(result["mood"], dict) and "patterns" in result["mood"], \
                    f"`mood` must be an object with `patterns`, got {result['mood']!r}"
                return result
            result = json_call(prompt, normalize)
            profiles.append({"era": era, "profile": result, "commit_count": len(window)})
            prior_lines.append(
                f"Era {i+1} \"{era['name']}\": "
                f"cast — {result['cast'].get('narrative', '')} "
                f"mood — {result['mood'].get('narrative', '')}"
            )
        return profiles

    def post(self, shared, prep_res, exec_res):
        shared["profiles"] = exec_res


# Step 4. Read the graveyard of killed features.
class Graveyard(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        min_files = shared.get("grave_min_files", 8)
        max_graves = shared.get("max_graves", 6)
        candidates = sorted(
            (c for c in shared["bulk_dels"]
             if c["count"] >= min_files and not _is_noise_deletion(c)),
            key=lambda c: c["count"], reverse=True,
        )
        # Keep the graves distinct: at most one per source area (first two path
        # components of the scope) so we don't return six variants of one deletion.
        graves, seen_areas = [], set()
        for c in candidates:
            if len(graves) >= max_graves:  # coderay-q2r.40: checked first, so 0 means none
                break
            area = os.sep.join(c["scope"].split(os.sep)[:2])
            if area in seen_areas:
                continue
            seen_areas.add(area)
            graves.append(c)
        return {
            "repo_path": shared["repo_path"],
            "eras": shared["eras"],
            "graves": graves,
            "template": load_prompt("graveyard-entry.md"),
        }

    def exec(self, ctx):
        entries = []
        for c in ctx["graves"]:
            print(f"  Graveyard: {c['hash'][:7]} ({c['count']} files) {c['subject'][:60]}")
            era = _era_for(c["month"], ctx["eras"]) or {}
            prompt = fill(
                ctx["template"],
                hash=c["hash"][:7], subject=c["subject"], author=c["author"], date=c["date"],
                era_name=era.get("name", "unknown"),
                era_start=era.get("start", ""), era_end=era.get("end", ""),
                era_description=era.get("description", ""),
                diff=gl.show_diff(ctx["repo_path"], c["hash"], max_chars=12000, stat=True),
            )
            entries.append({"commit": c, "era": era, "entry_md": call_llm(prompt).strip()})
        return entries

    def post(self, shared, prep_res, exec_res):
        shared["graves"] = exec_res
        print(f"  Wrote {len(exec_res)} graveyard entries")
