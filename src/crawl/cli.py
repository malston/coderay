"""crawl: dispatches to a named analysis subcommand."""
import argparse
import contextlib
import sys
from importlib.metadata import version

from crawl.analyses import ANALYSES
from crawl.core.call_llm import max_output_tokens
from crawl.core.env import env_defaults, load_dotenv
from crawl.core.estimate import estimate, format_estimate, resolve_for_estimate
from crawl.core.preview import aborted, format_preview
from crawl.core.runner import require_directory

ESTIMATE = "estimate-token-usage"

# A flag a real run takes that has no meaning here: nothing is written, so
# accepting it would promise the user an output that never appears.
NOT_PREVIEWABLE = ("--out",)


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
    # Before any provider is resolved, so the key can live in .env rather than
    # in the shell where every other process would inherit it (coderay-ebq).
    load_dotenv()

    parser = argparse.ArgumentParser(prog="crawl")
    parser.add_argument("--version", action="version", version=f"crawl {version('crawl')}")
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    _add_analysis_parsers(subparsers, previewing=False)

    # The same table again, one level down, so each analysis's own flags reach
    # its crawl step and the preview reflects the run it previews. A flag the
    # crawl step ignores is still accepted, so the command line matches a real
    # run -- tour's --codebase-budget sizes prompts no file crawl reaches.
    estimate_parser = subparsers.add_parser(ESTIMATE)
    _add_analysis_parsers(
        estimate_parser.add_subparsers(dest="estimate_analysis", required=True),
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
            plan = None if aborted(result) else analysis.prompt_plan(args, result)
        print(format_preview(analysis.NAME, args.repo_path, result))
        # A crawl that found nothing has no run to size, and a zero-dollar
        # estimate under an abort note would read as a real answer.
        if plan is not None:
            provider, model, assumed = resolve_for_estimate()
            # The real run wraps its whole flow in these, so the estimate has to
            # see the same LLM_MAX_OUTPUT_TOKENS or its worst case is wrong for
            # the four analyses that raise it (coderay-5wu.26).
            with env_defaults(getattr(analysis, "ENV_DEFAULTS", {})):
                cap = max_output_tokens()
            print(format_estimate(estimate(plan, provider, model, cap, assumed),
                                  getattr(args, "codebase_budget", None)))
        return
    ANALYSES[args.analysis].run(args)

if __name__ == "__main__":
    main()
