"""Turn a repo's git log into structured data the Ch6 prompts can read.

`git_log_commits` is the twenty-line crawler from listing 6.2, kept faithful to
the book: one dict per commit (hash, month, author, subject, files). Everything
else here is the compression the three prompts need:

  - name-eras   wants a bird's-eye view: directory-by-month activity, when each
                directory was born or went silent, and the biggest bulk
                additions/deletions (`heatmap`, `pivots`, `bulk_changes`).
  - profile-era wants one era's commits as a stream plus a few landmark diffs
                sampled across its arc (`era_commits`, `landmarks`, `show_diff`).
  - graveyard   wants the full diff of one bulk deletion (`show_diff`).

Everything reads git through `subprocess`; nothing here calls an LLM.
"""
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone

from crawl.core import credential_named

# coderay-q2r.35. The record separator is NUL: git refuses it in a commit
# message and no filesystem stores it in a path, so a hostile subject cannot
# split one log entry into two and choose the fields of the second (0x1e, the
# ASCII record separator, was allowed inside a subject and did exactly that).
# Each record head is then validated whole before anything is unpacked or
# parsed: a hash of 40 hex (SHA-1) or 64 hex (SHA-256), a numeric timestamp,
# an author without `|`, and the subject. show_diff peels its argument to a
# commit and passes --end-of-options, so a hash could neither be read as a git
# option nor name a blob (`git show <blob>` prints it raw, with no diff header
# for the redactor to anchor on).
SEP = "\x00"
HEX_HASH = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_RECORD_HEAD = re.compile(r"([0-9a-f]{40}(?:[0-9a-f]{24})?)\|(\d{1,12})\|([^|]*)\|(.*)", re.DOTALL)

# coderay-q2r.36. Every header form `git show -p` emits for a file: plain diffs,
# and the combined diffs a merge prints. Anchored to line start so a removed
# body line that happens to read `-diff --git ...` is not mistaken for one.
_HUNK_HEADER = re.compile(r"(?m)^(diff --(?:git|cc|combined) )")


def _records(raw):
    """(hash, timestamp, author, subject, files) per validated record."""
    for entry in raw.split(SEP)[1:]:
        head, *files = entry.strip("\n").split("\n")
        m = _RECORD_HEAD.fullmatch(head)
        if not m:
            continue
        h, ts, author, subject = m.groups()
        yield h, int(ts), author, subject, [f for f in files if f]


def git_log_commits(repo_path):
    """One dict per commit: hash, month, author, subject, files (listing 6.2)."""
    raw = subprocess.check_output(
        ["git", "-C", repo_path, "log",
         f"--pretty=format:%x00%H|%at|%an|%s", "--name-only"],
        text=True, errors="replace",
    )
    commits = []
    for h, ts, author, subject, files in _records(raw):
        dt = datetime.fromtimestamp(ts, timezone.utc)
        commits.append({
            "hash": h, "month": dt.strftime("%Y-%m"),
            "author": author, "subject": subject,
            "files": files,
        })
    return commits


def scope_of(files, depth=2):
    """The most-specific folder the files in a commit share.

    A commit that only touches `core/server/services/members/*` scopes to
    `core/server`; one that sprawls across the repo scopes to the top-level dir
    they share (often ``""`` for a repo-wide change). `depth` caps how deep a
    single shared prefix is reported so the label stays readable.
    """
    dirs = [os.path.dirname(f) for f in files if f]
    if not dirs:
        return ""
    common = os.path.commonpath(dirs) if len(dirs) > 1 else dirs[0]
    parts = common.split(os.sep)
    return os.sep.join(parts[:depth])


def bulk_changes(repo_path, status, min_files=10):
    """Commits that added (status='A') or deleted (status='D') >= min_files files.

    `--diff-filter` restricts BOTH which commits appear and which file paths are
    listed, so with `status='D'` the file list is exactly the deleted files.
    """
    raw = subprocess.check_output(
        ["git", "-C", repo_path, "log", f"--diff-filter={status}",
         "--name-only", f"--pretty=format:%x00%H|%at|%an|%s"],
        text=True, errors="replace",
    )
    out = []
    for h, ts, author, subject, files in _records(raw):
        if len(files) < min_files:
            continue
        dt = datetime.fromtimestamp(ts, timezone.utc)
        out.append({
            "hash": h, "date": dt.strftime("%Y-%m-%d"), "month": dt.strftime("%Y-%m"),
            "author": author, "subject": subject,
            "files": files, "count": len(files), "scope": scope_of(files),
        })
    return out


def dir_month_counts(commits, depth=2):
    """{directory: Counter(month -> commit count)}. One commit counts once per
    distinct directory it touches, so a repo-wide commit doesn't dwarf the rest."""
    counts = defaultdict(Counter)
    for c in commits:
        touched = {scope_of([f], depth=depth) for f in c["files"]}
        for d in touched:
            if d:
                counts[d][c["month"]] += 1
    return counts


def _top_dirs(counts, k):
    return sorted(counts, key=lambda d: sum(counts[d].values()), reverse=True)[:k]


def heatmap_summary(commits, top_k=25, depth=2):
    """Compact directory-by-month view: for each busy directory, its active span,
    peak month, and total commits. Stands in for the full (too big to paste) matrix."""
    counts = dir_month_counts(commits, depth=depth)
    lines = []
    for d in _top_dirs(counts, top_k):
        months = counts[d]
        peak_month, peak = months.most_common(1)[0]
        span = sorted(months)
        lines.append(
            f"{d}/  active {span[0]}..{span[-1]}  peak {peak_month} ({peak} commits)  "
            f"total {sum(months.values())}"
        )
    return "\n".join(lines)


def pivots_summary(commits, top_k=25, depth=2):
    """When each busy directory was born and when it went quiet: the signal for a
    directory appearing (a new bet) or falling silent (an abandoned one)."""
    counts = dir_month_counts(commits, depth=depth)
    all_months = sorted({c["month"] for c in commits})
    repo_end = all_months[-1] if all_months else ""
    lines = []
    for d in _top_dirs(counts, top_k):
        span = sorted(counts[d])
        born, last = span[0], span[-1]
        flag = "  <- went silent" if last < repo_end else ""
        lines.append(f"{d}/  born {born}  last active {last}{flag}")
    return "\n".join(lines)


def _changes_summary(changes, top_k=20):
    lines = []
    for c in sorted(changes, key=lambda c: c["count"], reverse=True)[:top_k]:
        lines.append(f"{c['hash']}  {c['date']}  {c['count']} files  {c['scope']}/  {c['subject']}")
    return "\n".join(lines)


def additions_summary(repo_path, min_files=10, top_k=20):
    return _changes_summary(bulk_changes(repo_path, "A", min_files), top_k)


def deletions_summary(repo_path, min_files=10, top_k=20):
    return _changes_summary(bulk_changes(repo_path, "D", min_files), top_k)


def commits_ascending(commits):
    """git log is newest-first; the era passes read the story oldest-first."""
    return list(reversed(commits))


def era_commits(commits_asc, start, end):
    """Every commit whose month falls in [start, end] (inclusive, YYYY-MM strings)."""
    return [c for c in commits_asc if start <= c["month"] <= end]


def sample_commits(commits, max_n):
    """Thin a long era to at most max_n commits by even stride, keeping the first
    and last. A 17k-commit era pasted whole overwhelms the model; an evenly
    sampled slice keeps the same shape (who, what, when) at a size it reads well."""
    if not max_n or len(commits) <= max_n:
        return commits, False
    step = len(commits) / max_n
    idx = sorted({0, len(commits) - 1} | {int(i * step) for i in range(max_n)})
    return [commits[i] for i in idx], True


def commit_stream(commits):
    """One line per commit: `month | author | scope | subject`."""
    return "\n".join(
        f"{c['month']} | {c['author']} | {scope_of(c['files'])}/ | {c['subject']}"
        for c in commits
    )


def landmarks(era):
    """Five commits sampled across an era's arc: opening, a peak in each third,
    and closing. Each anchors a real diff so the model can't guess from subjects."""
    if not era:
        return []
    picks = [("opening", era[0])]
    n = len(era)
    for label, chunk in (("early", era[:n // 3 or 1]),
                         ("mid", era[n // 3:2 * n // 3] or era),
                         ("late", era[2 * n // 3:] or era)):
        peak_month = Counter(c["month"] for c in chunk).most_common(1)[0][0]
        rep = max((c for c in chunk if c["month"] == peak_month),
                  key=lambda c: len(c["files"]))
        picks.append((label, rep))
    picks.append(("closing", era[-1]))
    # De-dup by hash while preserving the five slots (tiny eras can repeat commits).
    return picks


def is_secret_path(path):
    """True if a file's CONTENTS must never reach a prompt.

    The crawlers' own credential-name rule, so the graveyard redacts every
    file a crawler refuses by name (coderay-q2r.62).
    """
    return credential_named(os.path.basename(path))


def redact_secret_files(diff_text):
    """Drop the body of every file hunk whose path is credential-bearing.

    The graveyard reads bulk DELETIONS, and deleting a committed secret is one
    of the ordinary reasons a file gets deleted -- so `git show -p` on exactly
    the commits this analysis is most interested in hands the model a .env or a
    .pem in full, and it goes to a third-party API (coderay-q2r.34).

    The path stays, and so does the `--stat` summary above it: that a secret
    file was removed is real signal the analysis should report. Only the
    contents go. Filtering here rather than with a git pathspec keeps the stat
    intact, which an `:(exclude)` would also strip.
    """
    parts = _HUNK_HEADER.split(diff_text)  # [preamble, header, hunk, header, hunk, ...]
    out = [parts[0]]
    for header, hunk in zip(parts[1::2], parts[2::2]):
        path = hunk.split("\n", 1)[0]
        if any(is_secret_path(p) for p in _hunk_paths(header, hunk)):
            out.append(f"{header}{path}\n[contents omitted: credential-bearing file]\n")
        else:
            out.append(header + hunk)
    return "".join(out)


def _hunk_paths(header, hunk):
    """Every path a hunk header names, spaces intact.

    git never quotes a space, so `diff --git a/x y b/x y` cannot be tokenised;
    splitting on the last ` b/` recovers both sides whole, and a combined
    (`--cc`) header carries its one path as the rest of the line. The tokenised
    form stays as a fallback.
    """
    first = hunk.split("\n", 1)[0]
    paths = set()
    if header.startswith("diff --git "):
        a, sep, b = first.rpartition(" b/")
        if sep:
            paths.update((_unquote(a), _unquote(b)))
    else:
        paths.add(_unquote(first))
    paths.update(_unquote(p) for p in first.split() if p)
    return {p for p in paths if p}


def _unquote(token):
    """A header path token as a plain path: git C-quotes paths with non-ASCII,
    quotes or control characters, and a/ b/ are prefixes, not a character set."""
    return token.strip('"').removeprefix("a/").removeprefix("b/")


def show_diff(repo_path, commit_hash, max_chars=4000, stat=True):
    """`git show` for one commit, truncated. `stat=True` prepends the file summary.

    The patch body is filtered before truncation, so a credential-bearing file
    never reaches the caller regardless of where the cut lands.
    """
    cmd = ["git", "-C", repo_path, "show", "-p", "--no-color", *(["--stat"] if stat else []),
           "--end-of-options", f"{commit_hash}^{{commit}}"]
    raw = redact_secret_files(subprocess.check_output(cmd, text=True, errors="replace"))
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "\n... [diff truncated]"
    return raw


def repo_root(repo_path):
    """The repository root, or SystemExit if `repo_path` is not it.

    `git -C` walks up to the enclosing .git, so a plain folder inside any repo
    would otherwise be analysed as its parent, under the wrong name, and the
    parent's full history would go to the model (coderay-q2r.38).
    """
    probe = subprocess.run(["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(f"{repo_path}: {probe.stderr.strip() or 'not a git repository'}")
    top = probe.stdout.strip()
    # samefile, not string equality: a case-insensitive filesystem accepts
    # ~/Code/repo for an on-disk ~/code/repo, and git reports the on-disk case.
    if not os.path.samefile(top, repo_path):
        raise SystemExit(f"{repo_path} is not the root of a git repository "
                         f"(git resolves it to {top}); pass the repository root")
    return os.path.realpath(top)


def is_shallow(repo_path):
    """True for a --depth clone, whose log is a fragment of the history (coderay-q2r.38)."""
    return subprocess.check_output(
        ["git", "-C", repo_path, "rev-parse", "--is-shallow-repository"],
        text=True).strip() == "true"
