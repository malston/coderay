"""Apply an analysis's environment defaults for the length of one run."""
import contextlib
import os

@contextlib.contextmanager
def env_defaults(defaults):
    """Set each key only when it is absent or blank, then restore the prior
    environment.

    A value the user already set always wins. Blank counts as absent because
    sourcing .env.example exports every knob as the empty string. Restoring on
    exit keeps one analysis's default from leaking into the next under
    `crawl all`.
    """
    prior = {}
    try:
        for key, value in defaults.items():
            prior[key] = os.environ.get(key)
            if not prior[key]:
                os.environ[key] = value
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
