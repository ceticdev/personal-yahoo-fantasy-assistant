"""Environment-driven configuration. No secrets or tokens live in code.

`load_config()` loads the repository `.env` first (see `env.py`), so a
module-level `_config = load_config()` in `server.py` sees `.env` values even
when the process was started by the installed console script from an
unrelated working directory. Real environment variables always win over
`.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .env import load_env
from .logging_utils import register_secret


DEFAULT_TOKEN_PATH = Path.home() / ".config" / "yahoo-fantasy-mcp" / "token.json"
DEFAULT_CACHE_TTL_SECONDS = 120
READ_ONLY_SCOPE = "fspt-r"


@dataclass(frozen=True, slots=True)
class Config:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    token_path: Path
    default_league_key: str | None
    default_team_key: str | None
    cache_ttl_seconds: int
    log_level: str

    #: The `.env` file that was loaded for this config, if any. Diagnostic only.
    env_file: str | None = None

    @property
    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)


def load_config(*, use_dotenv: bool = True) -> Config:
    """Build configuration from the environment, after loading `.env`.

    Set `use_dotenv=False` to read only the real process environment (used by
    tests that assert precedence explicitly).
    """

    env_file = load_env() if use_dotenv else None

    token_path_raw = os.getenv("YAHOO_FANTASY_MCP_TOKEN_PATH", "").strip()
    ttl_raw = os.getenv("YAHOO_FANTASY_MCP_CACHE_TTL_SECONDS", "").strip()
    try:
        ttl = int(ttl_raw) if ttl_raw else DEFAULT_CACHE_TTL_SECONDS
    except ValueError:
        ttl = DEFAULT_CACHE_TTL_SECONDS

    client_secret = os.getenv("YAHOO_CLIENT_SECRET") or None
    # Registering the secret means it is struck from any log line that ever
    # manages to contain it, regardless of how it got there.
    register_secret(client_secret)

    return Config(
        client_id=os.getenv("YAHOO_CLIENT_ID") or None,
        client_secret=client_secret,
        redirect_uri=os.getenv("YAHOO_REDIRECT_URI", "oob"),
        token_path=Path(token_path_raw) if token_path_raw else DEFAULT_TOKEN_PATH,
        default_league_key=os.getenv("YAHOO_FANTASY_DEFAULT_LEAGUE_KEY") or None,
        default_team_key=os.getenv("YAHOO_FANTASY_DEFAULT_TEAM_KEY") or None,
        cache_ttl_seconds=ttl,
        log_level=os.getenv("YAHOO_FANTASY_MCP_LOG_LEVEL", "INFO").upper(),
        env_file=str(env_file) if env_file else None,
    )
