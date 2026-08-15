"""Environment-driven configuration. No secrets or tokens live in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)


def load_config() -> Config:
    token_path_raw = os.getenv("YAHOO_FANTASY_MCP_TOKEN_PATH", "").strip()
    ttl_raw = os.getenv("YAHOO_FANTASY_MCP_CACHE_TTL_SECONDS", "").strip()
    try:
        ttl = int(ttl_raw) if ttl_raw else DEFAULT_CACHE_TTL_SECONDS
    except ValueError:
        ttl = DEFAULT_CACHE_TTL_SECONDS

    return Config(
        client_id=os.getenv("YAHOO_CLIENT_ID") or None,
        client_secret=os.getenv("YAHOO_CLIENT_SECRET") or None,
        redirect_uri=os.getenv("YAHOO_REDIRECT_URI", "oob"),
        token_path=Path(token_path_raw) if token_path_raw else DEFAULT_TOKEN_PATH,
        default_league_key=os.getenv("YAHOO_FANTASY_DEFAULT_LEAGUE_KEY") or None,
        default_team_key=os.getenv("YAHOO_FANTASY_DEFAULT_TEAM_KEY") or None,
        cache_ttl_seconds=ttl,
        log_level=os.getenv("YAHOO_FANTASY_MCP_LOG_LEVEL", "INFO").upper(),
    )
