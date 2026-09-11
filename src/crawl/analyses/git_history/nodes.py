"""Git-history nodes: read a product's story out of its git history.

Four steps, each a slice of the same commit list:
  1. FetchHistory  run the crawler; pull bulk additions/deletions once
  2. NameEras      compress 13 years into 3-5 named eras (bird's-eye)
  3. ProfileEras   for each era, the cast (who) and mood (what) — one era at a time
  4. Graveyard     read the code of the biggest deletions: the bets they killed

Reliability mirrors the rest of the repo: every LLM node uses
Node(max_retries=3, wait=2), JSON parsing is strict so bad output retries, and
gitlog's subprocess reads raise on any git failure rather than reporting no
data, the one exception being a checkout with no commits, which FetchHistory
refuses outright instead.
"""
import re
from importlib import resources

from pocketflow import Node

from crawl.core import call_llm, DEFAULT_SKIP_DIR, read_prompt, fill, json_call
from crawl.core.render import printable
from . import gitlog as gl

PROMPTS_DIR = resources.files("crawl.analyses.git_history") / "prompts"


def load_prompt(name):
    return read_prompt(PROMPTS_DIR, name)


def _is_noise_deletion(change):
    """True when a bulk deletion is vendored/build/test churn, not a killed feature.

    Removing `node_modules/` (thousands of files) or a `dist/` build dwarfs every
    real deletion by raw count, so ranking by size alone buries the actual graves.
    A deletion is noise when most of its files sit under a skip-list directory
    (the same set the crawler prunes: node_modules, vendor, dist, build, tests, …).

    Git always emits forward-slash paths, so the split is on '/' rather than
    the platform's `os.sep` -- on Windows that would leave every path a single
    un-split token and this check would never fire (coderay-q2r.44)."""
    files = change["files"]
    noisy = sum(1 for f in files if set(f.split("/")) & DEFAULT_SKIP_DIR)
    return noisy > len(files) * 0.5


def _era_for(month, eras):
    """The era whose [start, end] window contains a YYYY-MM month (or None)."""
    for e in eras:
        if e["start"] <= month <= e.get("end", "9999-99"):
            return e
    return None  # coderay-q2r.40: not the last era, which mislabels a gap


def _excluding_pure_renames(candidates, repo_path, diff_filter):
    """bulk_changes runs with --no-renames so a directory move shows up as a
    plain deletion on its old paths and a plain addition on its new ones
    (coderay-q2r.44); a move isn't a killed feature or a real launch, and
    NameEras' survey must not describe one as either (coderay-6ts.1,
    coderay-ziw.2). `diff_filter` must match how `candidates` was collected
    ("D" for bulk_dels, "A" for bulk_adds) -- is_pure_rename's own docstring
    explains why the two aren't interchangeable. Required rather than
    defaulted: is_pure_rename returns True vacuously for a commit with zero
    paths of the given status, so a caller that forgets to state its status
    would fail silently instead of loudly (coderay-ziw.2 review).

    Called last, after every cheap in-memory filter has already narrowed
    `candidates`: is_pure_rename shells out to `git show`, so checking it
    before a candidate count/noise filter would run that subprocess on
    entries the cheap filters would have dropped anyway.

    Graveyard does its own is_pure_rename check inline instead of calling
    this (coderay-6ts.3): its candidates are further trimmed by max_graves
    and one-per-area dedup, both cheaper than a subprocess call, so it checks
    is_pure_rename only on a candidate that has already survived both."""
    return [c for c in candidates if not gl.is_pure_rename(repo_path, c["hash"], diff_filter)]


# Step 1. Crawl the log; pull the bulk-change rosters once.
# How many files a single commit must touch to read as one deliberate act
# rather than ordinary work. Additions run higher: a new feature lands in more
# files than the one it replaces.
BULK_ADD_FLOOR = 10
BULK_DEL_FLOOR = 5

# coderay-q2r.38. Shared with this analysis's preview(), so the pre-flight
# report and the run warn in the same words.
SHALLOW_WARNING = ("This is a shallow clone; the log is a fragment of the history "
                   "and the eras will be wrong. Unshallow it first "
                   "(git fetch --unshallow).")

NO_COMMITS = ("This checkout has no commits, so there is no history to read. "
              "Every pass here summarises the log; over an empty one they would "
              "name eras that never happened.")


class FetchHistory(Node):
    def prep(self, shared):
        return shared["repo_path"]

    def exec(self, repo_path):
        commits = gl.git_log_commits(repo_path)
        return {
            "commits": commits,
            "commits_asc": gl.commits_ascending(commits),
            "bulk_adds": gl.bulk_changes(repo_path, "A", min_files=BULK_ADD_FLOOR),
            "bulk_dels": gl.bulk_changes(repo_path, "D", min_files=BULK_DEL_FLOOR),
            "shallow": gl.is_shallow(repo_path),
        }

    def post(self, shared, prep_res, exec_res):
        c = exec_res["commits"]
        if not c:
            # SystemExit, not assert: python -O strips asserts, and four paid
            # passes would run over nothing (coderay-q2r.50). Before this the
            # empty log reached NameEras, which built a full prompt out of
            # "(none)" and invented eras from it.
            raise SystemExit(NO_COMMITS)
        shared.update(exec_res)
        span = f"{exec_res['commits_asc'][0]['month']}..{exec_res['commits_asc'][-1]['month']}" if c else "empty"
        print(f"  Crawled {len(c):,} commits ({span}), "
              f"{len(exec_res['bulk_adds'])} bulk adds, {len(exec_res['bulk_dels'])} bulk deletions")
        if exec_res["shallow"]:
            print(f"  WARNING: {SHALLOW_WARNING}")


_YEAR_MONTH = re.compile(r"\d{4}-\d{2}")


# Step 2. Name the eras from a bird's-eye survey.
class NameEras(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        commits = shared["commits"]
        big_dels = _excluding_pure_renames(
            [c for c in shared["bulk_dels"] if c["count"] >= 10], shared["repo_path"], "D")
        big_adds = _excluding_pure_renames(shared["bulk_adds"], shared["repo_path"], "A")
        prompt = fill(
            load_prompt("name-eras.md"),
            heatmap_summary=gl.heatmap_summary(commits),
            pivots_summary=gl.pivots_summary(commits),
            deletions_summary=gl._changes_summary(big_dels) or "(none)",
            additions_summary=gl._changes_summary(big_adds) or "(none)",
        )
        # The bulk-change lines carry each commit's subject verbatim (coderay-3eu).
        listed = [c["hash"] for c in gl.top_changes(big_dels) + gl.top_changes(big_adds)]
        return prompt, listed

    def exec(self, inputs):
        prompt, _listed = inputs
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
        shared["survey_commits_sent"] = prep_res[1]
        print(f"  Named {len(exec_res)} eras: " + " -> ".join(printable(e["name"], 60) for e in exec_res))


# Step 3. Profile each era's cast and mood, one era at a time.
class ProfileEras(Node):
    """A plain Node, not a BatchNode: each era's prompt carries the previous
    eras' summaries for cross-era contrast, so they run in sequence."""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        # Each era is a paid call, so finished profiles land in shared one at a
        # time: a failure that ends the run leaves the ones already bought for
        # the run-state dump, and a retry attempt resumes after them instead of
        # asking again (coderay-5wu.3, the pattern WriteChapters uses). exec
        # sees no shared, so it is handed the list.
        shared["profiles"] = []
        return {
            "repo_path": shared["repo_path"],
            "commits_asc": shared["commits_asc"],
            "eras": shared["eras"],
            "max_commits": shared.get("profile_max_commits", 400),
            "diff_chars": shared.get("profile_diff_chars", 2500),
            "template": load_prompt("profile-era.md"),
            "profiles": shared["profiles"],
        }

    def exec(self, ctx):
        eras, template = ctx["eras"], ctx["template"]
        profiles = ctx["profiles"]
        # An era whose window holds no commits is skipped below, so a profile's
        # position does not track its era's. Identity, not index, says which
        # ones an earlier attempt already answered.
        done = {_era_key(p["era"]) for p in profiles}
        prior_lines = [_prior_line(i, p) for i, p in enumerate(profiles)]
        for i, era in enumerate(eras):
            if _era_key(era) in done:
                continue  # answered on an earlier attempt
            print(f"  Profiling era {i+1}/{len(eras)}: {printable(era['name'], 80)}")
            window = gl.era_commits(ctx["commits_asc"], era["start"], era["end"])
            if not window:  # coderay-q2r.39
                print(f"  Era {printable(era['name'], 80)!r} ({era['start']}..{era['end']}) matches no "
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
            profiles.append({"era": era, "profile": result, "commit_count": len(window),
                             # what left the machine for this era (coderay-3eu)
                             "commits_sent": [c["hash"] for c in sampled],
                             "diffs_sent": list(dict.fromkeys(c["hash"] for c in diffs.values()))})
            prior_lines.append(_prior_line(i, profiles[-1]))
        return profiles

    def post(self, shared, prep_res, exec_res):
        shared["profiles"] = exec_res


def _era_key(era):
    """What identifies an era across attempts, since its index does not."""
    return (era.get("name", ""), era.get("start", ""), era.get("end", ""))


def _prior_line(index, profile):
    """One era's summary as the next era's prompt sees it. Rebuilt from shared
    on a resumed attempt, so the prompt is byte-identical either way and the
    response cache still hits."""
    result = profile["profile"]
    return (f"Era {index+1} \"{profile['era']['name']}\": "
            f"cast \u2014 {result['cast'].get('narrative', '')} "
            f"mood \u2014 {result['mood'].get('narrative', '')}")


# Step 4. Read the graveyard of killed features.
class Graveyard(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        min_files = shared.get("grave_min_files", 8)
        max_graves = shared.get("max_graves", 6)
        repo_path = shared["repo_path"]
        candidates = sorted(
            (c for c in shared["bulk_dels"]
             if c["count"] >= min_files and not _is_noise_deletion(c)),
            key=lambda c: c["count"], reverse=True,
        )
        # Keep the graves distinct: at most one per source area so we don't
        # return six variants of one deletion. `scope` is already the shared
        # prefix capped at two path components (gitlog.scope_of), so it IS
        # the area. is_pure_rename (a `git show` subprocess) is checked last,
        # only for a candidate that has already survived max_graves and area
        # dedup, both cheaper in-memory checks (coderay-6ts.3): a candidate
        # dropped by either never reaches the subprocess call.
        graves, seen_areas = [], set()
        for c in candidates:
            if len(graves) >= max_graves:  # coderay-q2r.40: checked first, so 0 means none
                break
            area = c["scope"]
            if area in seen_areas:
                continue
            if gl.is_pure_rename(repo_path, c["hash"], "D"):
                continue
            seen_areas.add(area)
            graves.append(c)
        # Finished entries land in shared one at a time, for the same reason
        # ProfileEras does it (coderay-5wu.3).
        shared["graves"] = []
        return {
            "repo_path": shared["repo_path"],
            "eras": shared["eras"],
            "graves": graves,
            "template": load_prompt("graveyard-entry.md"),
            "entries": shared["graves"],
        }

    def exec(self, ctx):
        entries = ctx["entries"]
        done = {e["commit"]["hash"] for e in entries}
        for c in ctx["graves"]:
            if c["hash"] in done:
                continue  # written on an earlier attempt
            print(f"  Graveyard: {c['hash'][:7]} ({c['count']} files) {printable(c['subject'], 60)}")
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
