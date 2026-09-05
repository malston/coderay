"""Model text made safe for the terminal.

Lives apart from the renderer so the LLM layer can use it in its own error
messages without importing the renderer, which imports the LLM layer.
"""
import unicodedata


def _is_visible(ch):
    # Cc is the control characters (C0, DEL, C1); Cf the format characters
    # (bidi overrides, zero-width joiners), which reorder or hide what follows.
    return unicodedata.category(ch) not in ("Cc", "Cf") or ch in " \t\n\r"


def printable(text, limit):
    """Model text for the terminal: control and format characters removed,
    whitespace collapsed, cut to `limit`, so a reply cannot move the cursor,
    reverse the line or fake a line of the run's own output."""
    return " ".join("".join(ch for ch in str(text or "") if _is_visible(ch)).split())[:limit]


def positive_int(raw):
    """A positive whole number from a knob's text (a flag or an environment
    variable). Raises ValueError with the reason; the caller wraps it in the
    error type its setting deserves."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        raise ValueError(f"{raw!r} is not a positive whole number")
    return n
