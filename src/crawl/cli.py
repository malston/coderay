"""crawl: dispatches to a named analysis subcommand."""
import argparse
import contextlib
import sys
from importlib.metadata import version

from crawl.analyses import ANALYSES
from crawl.core.preview import format_preview
from crawl.core.runner import require_directory

ESTIMATE = "estimate-token-usage"

# Flags a real run takes that have no meaning here: nothing is written, and the
# token estimate --dry-run promises is exactly what this command does not yet
# produce. Accepting either would promise the user an output that never appears.
NOT_PREVIEWABLE = ("--out", "--dry-run")


def _add_analysis_parsers(subparsers, previewing):
    """One subparser per analysis, reusing each analysis's own add_arguments so a
    flag is declared once. The preview parsers then drop the flags that only a
    real run can honour."""
    for name, analysis in ANALYSES.items():
        sub = subparsers.add_parser(name)
        sub.add_argument("repo_path")
        if not previewing:
            sub.add_argument("--out", default=None)
        analysis.add_arguments(sub)
        if previewing:
            _drop_arguments(sub, NOT_PREVIEWABLE)


def _drop_arguments(parser, flags):
    """Remove flags an analysis declared for its real run, so the preview refuses
    them with argparse's own "unrecognized arguments" rather than accepting one
    and silently doing nothing with it."""
    for action in [a for a in parser._actions if set(a.option_strings) & set(flags)]:
        parser._remove_action(action)
        for group in parser._action_groups:
            if action in group._group_actions:
                group._group_actions.remove(action)
        for option in action.option_strings:
            parser._option_string_actions.pop(option, None)


def main():
    parser = argparse.ArgumentParser(prog="crawl")
    parser.add_argument("--version", action="version", version=f"crawl {version('crawl')}")
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    _add_analysis_parsers(subparsers, previewing=False)

    # The same table again, one level down, so each analysis's own flags reach
    # its crawl step and the preview reflects the run it previews. A flag the
    # crawl step ignores is still accepted, so the command line matches a real
    # run -- tour's --codebase-budget sizes prompts no file crawl reaches.
    estimate = subparsers.add_parser(ESTIMATE)
    _add_analysis_parsers(estimate.add_subparsers(dest="estimate_analysis", required=True),
                          previewing=True)

    args = parser.parse_args()
    if args.analysis == ESTIMATE:
        analysis = ANALYSES[args.estimate_analysis]
        require_directory(args.repo_path)
        # The crawlers print progress in-band with a real run's log. Here stdout
        # is a single formatted report, so their chatter goes to stderr and the
        # report stays pipeable (coderay-pqj).
        with contextlib.redirect_stdout(sys.stderr):
            result = analysis.preview(args)
        print(format_preview(analysis.NAME, args.repo_path, result))
        return
    ANALYSES[args.analysis].run(args)

if __name__ == "__main__":
    main()
