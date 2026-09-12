"""Read the user's own settings, and apply an analysis's defaults for one run."""
import contextlib
import os

from dotenv import load_dotenv as _load_dotenv

# The file the README tells you to make: `cp .env.example .env`.
DOTENV = ".env"


def load_dotenv():
    """Read `.env` from the working directory into the environment.

    The API key has to reach this process without passing through the shell.
    Exported, it is inherited by everything else started in the repo -- Claude
    Code prefers an ANTHROPIC_API_KEY over its own login and bills whichever
    account the key belongs to (coderay-ebq).

    A variable already set always wins, so CI and a one-off override on the
    command line still beat the file.

    The working directory only, never a search upward: `crawl tour .` inside
    someone else's checkout must not pick up a `.env` sitting above it and send
    their key out under this user's name. A missing file is not an error.
    """
    _load_dotenv(dotenv_path=os.path.join(os.getcwd(), DOTENV), override=False)

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
