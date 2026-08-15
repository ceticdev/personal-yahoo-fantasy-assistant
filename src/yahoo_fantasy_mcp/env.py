"""Locate and load the repository `.env` before configuration is built.

Rules this module implements:

* Only a file named exactly `.env` is ever loaded. `.env.example` is a
  documentation artifact with placeholder values and is never read.
* Real process environment variables win. `.env` only fills in what the
  environment did not already define (`override=False`).
* Lookup works when the server is launched through the installed
  `yahoo-fantasy-mcp` console script from an unrelated working directory: we
  search upward from the current directory first, then upward from this
  package's own location (which finds the repo `.env` for an editable
  install).
* A missing `.env` is a normal, silent no-op -- the server is expected to run
  from real environment variables in plenty of setups.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILENAME = ".env"

#: Explicit override for operators who keep `.env` somewhere unusual.
ENV_PATH_VAR = "YAHOO_FANTASY_MCP_ENV_FILE"

#: Repo root when running from a source checkout / editable install:
#: <root>/src/yahoo_fantasy_mcp/env.py -> <root>
_PACKAGE_ANCHOR = Path(__file__).resolve()


def _search_upward(start: Path) -> Path | None:
    """Return the first `.env` at or above `start`, if any."""

    try:
        current = start.resolve()
    except OSError:  # pragma: no cover - unreadable cwd
        return None
    for directory in (current, *current.parents):
        candidate = directory / ENV_FILENAME
        if candidate.is_file():
            return candidate
    return None


def find_env_file(start: Path | None = None) -> Path | None:
    """Find the `.env` that should apply to this process.

    Order: explicit `YAHOO_FANTASY_MCP_ENV_FILE`, then upward from `start`
    (default: the current working directory), then upward from this package's
    own directory so a console script launched from anywhere still finds the
    repository `.env`.
    """

    explicit = os.environ.get(ENV_PATH_VAR, "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None

    origin = start if start is not None else Path.cwd()
    found = _search_upward(origin)
    if found is not None:
        return found
    return _search_upward(_PACKAGE_ANCHOR.parent)


def load_env(start: Path | None = None) -> Path | None:
    """Load the repository `.env` without overriding the real environment.

    Returns the path that was loaded, or None if no `.env` was found.
    """

    env_file = find_env_file(start)
    if env_file is None:
        return None
    # override=False is the precedence rule: anything already exported in the
    # real process environment stays authoritative.
    load_dotenv(env_file, override=False)
    return env_file
