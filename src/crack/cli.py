"""crack: dispatches to a named analysis subcommand."""
import argparse
from importlib.metadata import version

from crack.analyses import ANALYSES

def main():
    parser = argparse.ArgumentParser(prog="crack")
    parser.add_argument("--version", action="version", version=f"crack {version('crack')}")
    subparsers = parser.add_subparsers(dest="analysis", required=True)
    for name, analysis in ANALYSES.items():
        sub = subparsers.add_parser(name)
        sub.add_argument("repo_path")
        sub.add_argument("--out", default=None)
        analysis.add_arguments(sub)
    args = parser.parse_args()
    ANALYSES[args.analysis].run(args)

if __name__ == "__main__":
    main()
