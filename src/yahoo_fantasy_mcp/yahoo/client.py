"""Yahoo Fantasy Sports API client: cache-aware, redacted logging, typed errors.

Yahoo gates the Fantasy Sports API behind a manual per-app provisioning
queue. That is not a token problem, and refreshing the token will not fix it.
This client detects that specific failure mode and reports it as such instead
of retrying forever. See `VERIFICATION-NOTES.md`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx

from ..auth.oauth_client import YahooOAuthClient
from ..cache import TTLCache
from ..errors import (
    InputValidationError,
    YahooApiError,
    YahooNotProvisionedError,
    YahooServiceError,
    YahooTransportError,
    YahooUnauthorizedError,
    truncate_provider_body,
)
from ..logging_utils import log_context
from .parsers.league_settings import parse_league_settings
from .parsers.matchups import parse_weekly_matchups
from .parsers.players import parse_free_agents
from .parsers.roster import parse_team_roster
from .parsers.standings import parse_league_standings
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

# Yahoo status codes worth retrying later rather than treating as fatal.
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_LEAGUE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+\.l\.[A-Za-z0-9_-]+$")
_TEAM_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+\.l\.[A-Za-z0-9_-]+\.t\.[A-Za-z0-9_-]+$")
_FREE_AGENT_POSITIONS = frozenset({"QB", "WR", "RB", "TE", "K", "DEF"})


def _league_key(value: str) -> str:
    candidate = str(value).strip()
    if not _LEAGUE_KEY_RE.fullmatch(candidate):
        raise InputValidationError("league_key must look like '<game>.l.<league>'")
    return candidate


def _team_key(value: str) -> str:
    candidate = str(value).strip()
    if not _TEAM_KEY_RE.fullmatch(candidate):
        raise InputValidationError("team_key must look like '<game>.l.<league>.t.<team>'")
    return candidate


def _count(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise InputValidationError("count must be an integer from 1 through 100")
    return value


def _week(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputValidationError("week must be a positive integer")
    return value


def _position(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip().upper()
    if candidate not in _FREE_AGENT_POSITIONS:
        allowed = ", ".join(sorted(_FREE_AGENT_POSITIONS))
        raise InputValidationError(f"position must be one of: {allowed}")
    return candidate


@dataclass
class YahooFantasyClient:
    oauth_client: YahooOAuthClient
    cache: TTLCache
    logger: logging.Logger

    def _get_json(self, path: str) -> dict[str, Any]:
        """GET one Yahoo Fantasy resource.

        This is the only place this package talks to the Fantasy API, and it
        only ever issues GET. There is no PUT/POST/PATCH/DELETE path to Yahoo
        Fantasy anywhere in this codebase -- see
        `tests/contract/test_read_only_transport.py`.
        """

        token = self.oauth_client.get_valid_token()
        url = f"{BASE_URL}/{path}"
        params = {"format": "json"}
        headers = {"Authorization": f"Bearer {token.access_token}"}
        log_context(self.logger, logging.INFO, "yahoo_api_request", path=path)
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=15.0)
        except httpx.HTTPError as exc:
            log_context(
                self.logger,
                logging.ERROR,
                "yahoo_api_transport_error",
                path=path,
                error_type=type(exc).__name__,
            )
            raise YahooTransportError(
                f"Yahoo API unreachable for {path}: {type(exc).__name__}"
            ) from exc

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as exc:
                log_context(self.logger, logging.ERROR, "yahoo_api_bad_json", path=path)
                raise YahooServiceError(
                    f"Yahoo API returned a non-JSON body for {path}"
                ) from exc

        body = truncate_provider_body(response.text)
        if response.status_code == 403 or "additional_authorization_required" in body:
            log_context(self.logger, logging.WARNING, "yahoo_api_not_provisioned", path=path)
            raise YahooNotProvisionedError(NOT_PROVISIONED_MESSAGE)
        if response.status_code == 401:
            log_context(self.logger, logging.WARNING, "yahoo_api_unauthorized", path=path)
            raise YahooUnauthorizedError(
                f"Yahoo API rejected the token for {path} (401). Re-run "
                f"scripts/obtain_yahoo_token.py to re-authorize. Provider said: {body}"
            )
        if response.status_code in _RETRYABLE_STATUSES:
            log_context(
                self.logger,
                logging.WARNING,
                "yahoo_api_service_error",
                path=path,
                status=response.status_code,
            )
            raise YahooServiceError(
                f"Yahoo API error {response.status_code} for {path}: {body}"
            )

        log_context(self.logger, logging.ERROR, "yahoo_api_error", path=path, status=response.status_code)
        raise YahooApiError(f"Yahoo API error {response.status_code} for {path}: {body}")

    def _cached(self, cache_key: str, fetch: Callable[[], T], force_refresh: bool) -> dict[str, Any]:
        return self.cache.get_or_fetch(cache_key, fetch, force_refresh=force_refresh)

    def get_league_settings(self, league_key: str, force_refresh: bool = False) -> dict[str, Any]:
        league_key = _league_key(league_key)
        def fetch():
            data = self._get_json(f"league/{league_key}/settings")
            return parse_league_settings(data)

        return self._cached(f"league_settings:{league_key}", fetch, force_refresh)

    def get_team_roster(self, team_key: str, force_refresh: bool = False) -> dict[str, Any]:
        team_key = _team_key(team_key)
        def fetch():
            data = self._get_json(f"team/{team_key}/roster")
            return parse_team_roster(data)

        return self._cached(f"roster:{team_key}", fetch, force_refresh)

    def get_free_agents(
        self, league_key: str, position: str | None = None, count: int = 25, force_refresh: bool = False
    ) -> dict[str, Any]:
        league_key = _league_key(league_key)
        position = _position(position)
        count = _count(count)
        path = f"league/{league_key}/players;status=FA;count={count}"
        if position:
            path += f";position={position}"

        def fetch():
            data = self._get_json(path)
            return parse_free_agents(data)

        return self._cached(f"free_agents:{league_key}:{position}:{count}", fetch, force_refresh)

    def get_transactions(
        self, league_key: str, count: int = 25, force_refresh: bool = False
    ) -> dict[str, Any]:
        league_key = _league_key(league_key)
        count = _count(count)
        path = f"league/{league_key}/transactions;count={count}"

        def fetch():
            data = self._get_json(path)
            return parse_transactions(data)

        return self._cached(f"transactions:{league_key}:{count}", fetch, force_refresh)

    def get_league_standings(
        self, league_key: str, force_refresh: bool = False
    ) -> dict[str, Any]:
        league_key = _league_key(league_key)

        def fetch():
            data = self._get_json(f"league/{league_key}/standings")
            return parse_league_standings(data)

        return self._cached(f"standings:{league_key}", fetch, force_refresh)

    def get_weekly_matchups(
        self, league_key: str, week: int | None = None, force_refresh: bool = False
    ) -> dict[str, Any]:
        league_key = _league_key(league_key)
        week = _week(week)
        path = f"league/{league_key}/scoreboard"
        if week is not None:
            path += f";week={week}"

        def fetch():
            data = self._get_json(path)
            return parse_weekly_matchups(data)

        cache_week = "current" if week is None else str(week)
        return self._cached(f"matchups:{league_key}:{cache_week}", fetch, force_refresh)
