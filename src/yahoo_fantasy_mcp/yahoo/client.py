"""Yahoo Fantasy Sports API client: cache-aware, redacted logging, typed errors.

Yahoo gates the Fantasy Sports API behind a manual per-app provisioning
queue. That is not a token problem, and refreshing the token will not fix it.
This client detects that specific failure mode and reports it as such instead
of retrying forever. See `VERIFICATION-NOTES.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx

from ..auth.oauth_client import YahooOAuthClient
from ..cache import TTLCache
from ..logging_utils import log_context
from .parsers.league_settings import parse_league_settings
from .parsers.players import parse_free_agents
from .parsers.roster import parse_team_roster
from .parsers.transactions import parse_transactions

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

NOT_PROVISIONED_MESSAGE = (
    "Yahoo Fantasy Sports API access is gated behind a manual app-provisioning "
    "queue (oauth_problem=additional_authorization_required, or a bare 403). "
    "This is not a token problem -- refreshing will not help. See "
    "VERIFICATION-NOTES.md. Apply at "
    "https://sports.yahoo.com/developer/access/ with the existing client ID."
)

T = TypeVar("T")


class YahooApiError(RuntimeError):
    def __init__(self, message: str, *, not_provisioned: bool = False) -> None:
        super().__init__(message)
        self.not_provisioned = not_provisioned


@dataclass
class YahooFantasyClient:
    oauth_client: YahooOAuthClient
    cache: TTLCache
    logger: logging.Logger

    def _get_json(self, path: str) -> dict[str, Any]:
        token = self.oauth_client.get_valid_token()
        url = f"{BASE_URL}/{path}"
        params = {"format": "json"}
        headers = {"Authorization": f"Bearer {token.access_token}"}
        log_context(self.logger, logging.INFO, "yahoo_api_request", path=path)
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=15.0)
        except httpx.HTTPError as exc:
            log_context(self.logger, logging.ERROR, "yahoo_api_transport_error", path=path, error=str(exc))
            raise YahooApiError(f"Yahoo API unreachable for {path}: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        body = response.text[:300]
        if response.status_code == 403 or "additional_authorization_required" in body:
            log_context(self.logger, logging.WARNING, "yahoo_api_not_provisioned", path=path)
            raise YahooApiError(NOT_PROVISIONED_MESSAGE, not_provisioned=True)
        if response.status_code == 401:
            log_context(self.logger, logging.WARNING, "yahoo_api_unauthorized", path=path)
            raise YahooApiError(f"Yahoo API rejected the token for {path} (401): {body}")

        log_context(self.logger, logging.ERROR, "yahoo_api_error", path=path, status=response.status_code)
        raise YahooApiError(f"Yahoo API error {response.status_code} for {path}: {body}")

    def _cached(self, cache_key: str, fetch: Callable[[], T], force_refresh: bool) -> dict[str, Any]:
        return self.cache.get_or_fetch(cache_key, fetch, force_refresh=force_refresh)

    def get_league_settings(self, league_key: str, force_refresh: bool = False) -> dict[str, Any]:
        def fetch():
            data = self._get_json(f"league/{league_key}/settings")
            return parse_league_settings(data)

        return self._cached(f"league_settings:{league_key}", fetch, force_refresh)

    def get_team_roster(self, team_key: str, force_refresh: bool = False) -> dict[str, Any]:
        def fetch():
            data = self._get_json(f"team/{team_key}/roster")
            return parse_team_roster(data)

        return self._cached(f"roster:{team_key}", fetch, force_refresh)

    def get_free_agents(
        self, league_key: str, position: str | None = None, count: int = 25, force_refresh: bool = False
    ) -> dict[str, Any]:
        path = f"league/{league_key}/players;status=FA;count={int(count)}"
        if position:
            path += f";position={position}"

        def fetch():
            data = self._get_json(path)
            return parse_free_agents(data)

        return self._cached(f"free_agents:{league_key}:{position}:{count}", fetch, force_refresh)

    def get_transactions(
        self, league_key: str, count: int = 25, force_refresh: bool = False
    ) -> dict[str, Any]:
        path = f"league/{league_key}/transactions;count={int(count)}"

        def fetch():
            data = self._get_json(path)
            return parse_transactions(data)

        return self._cached(f"transactions:{league_key}:{count}", fetch, force_refresh)
