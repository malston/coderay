"""The pre-flight preview: what an analysis's crawl step found, before any LLM
call, and how it reads on a terminal.

Each analysis's `preview(args)` returns a `Preview`. The counts are deliberately
per-analysis -- only product-intent's crawler tracks included/dropped/unreadable,
and a count no crawler computed would be a number this command invented. Labels
are the reader's phrases, not field names, so each says what it counted.
"""
import textwrap
from typing import Dict, List, TypedDict


class Preview(TypedDict, total=False):
    """What a crawl step found. Not validated at runtime -- documents the contract.

    Always present:

    counts: label -> how many, in the order the reader should meet them.
    files:  label -> the repo-relative paths behind a count. Not every count has
            a list (backend matches a layer without reading the file) and not
            every analysis reads files at all (git-history reads commits).
    notes:  what the counts alone would misstate: a budget that capped text
            rather than dropping files, a refusal, or a real run that stops here.

    Present only where the crawler genuinely computes the quantity. The labels
    above are the reader's phrases, so a consumer that needs the kept or dropped
    set cannot find it by matching text; these three keys carry it under a fixed
    name. Absent means "this crawler computes no such quantity", which is the
    honest answer where a zero would be an invented count (coderay-05w.6):

    included:        the repo-relative paths whose text reached the prompts.
    dropped:         the repo-relative paths a budget or cap kept out of them.
                     Absent for a crawler that caps its assembled text instead of
                     dropping whole files (architecture), and for one that reads
                     no files at all (git-history).
    assembled_chars: the length of the text the crawl assembled. Carried so the
                     token estimate and the counts describe one crawl rather than
                     two, without re-running the crawl (coderay-05w.5).
    """
    counts: Dict[str, int]
    files: Dict[str, List[str]]
    notes: List[str]
    included: List[str]
    dropped: List[str]
    assembled_chars: int


def aborts(reason: str) -> str:
    """The note for a crawl that found nothing to send. Reporting zero rather than
    raising is right for a preview -- the user came to find out -- but reporting
    zero without saying the real run stops there leaves them guessing, and the
    crawl already knows why (the nodes raise this same reason, coderay-q2r.50)."""
    return f"A real run stops here: {reason}"


def format_preview(name: str, repo_path: str, result: Preview) -> str:
    """The report a reader sees: one aligned count per line, then anything the
    counts alone would misstate."""
    width = max((len(label) for label in result["counts"]), default=0)
    lines = [f"{name}: {repo_path}", ""]
    lines += [f"  {label[0].upper() + label[1:]:<{width}}  {count:,}"
              for label, count in result["counts"].items()]
    for note in result["notes"]:
        lines += ["", *textwrap.wrap(note, width=76, initial_indent="  NOTE: ",
                                     subsequent_indent="        ")]
    lines += ["", "  This reports the file crawl only; it does not yet estimate "
                  "tokens or cost."]
    return "\n".join(lines)
