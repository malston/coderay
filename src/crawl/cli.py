"""crawl: dispatches to a named analysis subcommand."""
import argparse
from importlib.metadata import version

from crawl.analyses import ANALYSES

ESTIMATE = "estimate-token-usage"


def format_preview(name, repo_path, result):
    """The preview as a reader sees it. Counts are not uniform across analyses:
    each crawler tracks what its own bundle needs, so each reports what it
    actually counted rather than a common triple it would have to invent."""
    width = max(len(label) for label in result["counts"])
    lines = [f"{name}: {repo_path}", ""]
    lines += [f"  {label:<{width}}  {count:,}" for label, count in result["counts"].items()]
    for note in result["notes"]:
        lines += ["", f"  NOTE: {note}"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(prog="crawl")
    parser.add_argument("--version", action="version", version=f"crawl {version('crawl')}")
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    for name, analysis in ANALYSES.items():
        sub = subparsers.add_parser(name)
        sub.add_argument("repo_path")
        sub.add_argument("--out", default=None)
        analysis.add_arguments(sub)

    # The same table again, one level down: each analysis's own flags reach the
    # crawl step so the preview reflects the exact run it is previewing. No
    # --out -- nothing is written, so accepting it would promise a file that
    # never appears.
    estimate = subparsers.add_parser(ESTIMATE)
    estimate_subparsers = estimate.add_subparsers(dest="estimate_analysis", required=True)
    for name, analysis in ANALYSES.items():
        sub = estimate_subparsers.add_parser(name)
        sub.add_argument("repo_path")
        analysis.add_arguments(sub)

    args = parser.parse_args()
    if args.analysis == ESTIMATE:
        analysis = ANALYSES[args.estimate_analysis]
        print(format_preview(analysis.NAME, args.repo_path, analysis.preview(args)))
        return
    ANALYSES[args.analysis].run(args)

if __name__ == "__main__":
    main()
