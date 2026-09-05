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
