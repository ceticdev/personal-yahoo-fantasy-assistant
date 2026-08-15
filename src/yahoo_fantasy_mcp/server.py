"""FastMCP entrypoint. Read-only tools only -- see docs/THREAT_MODEL.md.

No add/drop/trade/lineup-submit tool exists in this file. That is a design
decision, not a coverage gap: item 8 of the deferred-backlog list explicitly
defers provider writes until a separate confirmation-gated threat model is
approved. Do not add one without updating THREAT_MODEL.md first.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .auth.oauth_client import YahooOAuthClient
from .auth.token_vault import TokenVault
from .cache import TTLCache
from .config import load_config
from .logging_utils import configure_logging
from .optimizer.exact_slot import optimize_lineup as _optimize_lineup
from .projections.adapter import normalize_stat_line
from .projections.explosive_play_model import ExplosivePlayModel
from .serialization import to_jsonable
from .yahoo.client import YahooApiError, YahooFantasyClient

_config = load_config()
_logger = configure_logging(_config.log_level)
_cache = TTLCache(ttl_seconds=_config.cache_ttl_seconds)
_explosive_model = ExplosivePlayModel()

mcp = FastMCP(
    name="yahoo-fantasy-mcp-v2",
    instructions=(
        "Self-hosted, READ-ONLY Yahoo Fantasy Sports connector. Provides live Yahoo "
        "league settings (full stat-modifier and roster-position tables), rosters, "
        "free agents, and transactions, plus a projection normalizer, an "
        "explosive-play estimator, and an exact-slot lineup optimizer. "
        "There are no write tools in this server -- it cannot add, drop, trade, "
        "change lineups, or change league settings, even if asked. Every read is "
        "labeled with a source timestamp and a `stale` flag; treat `stale: true` "
        "as a reason to say so, not to hide it. For custom league scoring, use a "
        "separate scoring MCP -- this server normalizes stat lines but does not "
        "compute fantasy points itself."
    ),
)


def _client() -> YahooFantasyClient:
    if not _config.has_credentials:
        raise YahooApiError(
            "YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET are not set. Copy .env.example to "
            ".env and fill them in, then run scripts/obtain_yahoo_token.py once."
        )
    vault = TokenVault(_config.token_path)
    oauth_client = YahooOAuthClient(
        client_id=_config.client_id,
        client_secret=_config.client_secret,
        redirect_uri=_config.redirect_uri,
        vault=vault,
    )
    return YahooFantasyClient(oauth_client=oauth_client, cache=_cache, logger=_logger)


def _error_envelope(exc: YahooApiError) -> dict[str, Any]:
    return {
        "error": str(exc),
        "not_provisioned": getattr(exc, "not_provisioned", False),
        "data": None,
    }


@mcp.tool
def get_league_settings(league_key: str, force_refresh: bool = False) -> dict[str, Any]:
    """Full Yahoo league settings: stat modifiers, roster position counts, playoff/waiver rules.

    This is the table Flaim's get_league_info does not expose -- use it to
    cross-check a custom scoring engine against Yahoo's actual configured rules.
    """

    try:
        envelope = _client().get_league_settings(league_key, force_refresh=force_refresh)
    except YahooApiError as exc:
        return _error_envelope(exc)
    envelope["data"] = to_jsonable(envelope["data"])
    return envelope


@mcp.tool
def get_team_roster(team_key: str, force_refresh: bool = False) -> dict[str, Any]:
    """Current roster for a Yahoo team key, with status/status_full and selected_position."""

    try:
        envelope = _client().get_team_roster(team_key, force_refresh=force_refresh)
    except YahooApiError as exc:
        return _error_envelope(exc)
    envelope["data"] = to_jsonable(envelope["data"])
    return envelope


@mcp.tool
def get_free_agents(
    league_key: str, position: str | None = None, count: int = 25, force_refresh: bool = False
) -> dict[str, Any]:
    """Available free agents in the league, optionally filtered by position."""

    try:
        envelope = _client().get_free_agents(
            league_key, position=position, count=count, force_refresh=force_refresh
        )
    except YahooApiError as exc:
        return _error_envelope(exc)
    envelope["data"] = to_jsonable(envelope["data"])
    return envelope


@mcp.tool
def get_transactions(league_key: str, count: int = 25, force_refresh: bool = False) -> dict[str, Any]:
    """Recent league transactions (adds/drops/trades)."""

    try:
        envelope = _client().get_transactions(league_key, count=count, force_refresh=force_refresh)
    except YahooApiError as exc:
        return _error_envelope(exc)
    envelope["data"] = to_jsonable(envelope["data"])
    return envelope


@mcp.tool
def normalize_projection(
    stat_line: dict[str, float],
    source: str,
    volume: dict[str, float] | None = None,
    estimate_explosive_plays: bool = False,
) -> dict[str, Any]:
    """Normalize a raw stat line from any projection source into the shape a scoring engine expects.

    Does not compute fantasy points -- pass the returned `stat_line` to a
    scoring MCP. If `estimate_explosive_plays` is False (the default), missing
    40+ play counts are left unavailable and labeled as such rather than
    silently zeroed and forgotten. Set it to True and supply `volume`
    (pass_completions / rush_attempts / receptions) to get a labeled model
    estimate instead -- see the explosive-play model's `basis` field for
    whether that estimate is a fitted rate or an unfitted placeholder.
    """

    result = normalize_stat_line(
        stat_line,
        source=source,
        volume=volume,
        estimate_explosive_plays=estimate_explosive_plays,
        model=_explosive_model,
    )
    return result.as_dict()


@mcp.tool
def optimize_lineup(players: list[dict[str, Any]], slots: list[str]) -> dict[str, Any]:
    """Exact-slot lineup optimizer. Pass `slots` from get_league_settings' starter_slots.

    Ported from matty-fantasy-mcp, generalized to take the league's real slot
    list instead of a hardcoded one, so it can't silently drift out of sync
    with the league's actual roster settings.
    """

    return _optimize_lineup(players, slots)


@mcp.tool
def token_vault_status() -> dict[str, Any]:
    """Diagnostic: whether a Yahoo token is vaulted and its (redacted) expiry state.

    Never returns the access or refresh token itself.
    """

    vault = TokenVault(_config.token_path)
    token = vault.load()
    return {
        "vault_path": str(_config.token_path),
        "has_credentials_configured": _config.has_credentials,
        "token_present": token is not None,
        "token": token.redacted() if token else None,
    }


@mcp.resource("guide://weekly-workflow")
def weekly_workflow_resource() -> str:
    """Decision sequence for weekly roster management using this server."""

    return (
        "1. get_league_settings for the live stat-modifier and roster-slot tables; "
        "do not assume last week's settings still hold.\n"
        "2. get_team_roster, get_free_agents, and get_transactions for current state.\n"
        "3. For every player, normalize_projection the raw stat line from your "
        "projection source. Leave estimate_explosive_plays off unless you can supply "
        "real volume stats and accept a labeled model estimate.\n"
        "4. Pass normalized stat lines to a scoring MCP for points, then "
        "optimize_lineup with slots from step 1.\n"
        "5. Report any `stale: true` or `not_provisioned` result explicitly -- never "
        "present cached or blocked data as fresh.\n"
        "6. This server has no write tools. It cannot add/drop/trade/submit a lineup, "
        "and never will without a separate, explicitly approved change."
    )


def main() -> None:
    """Run the local MCP over stdio for Claude Desktop/Cowork-compatible clients."""

    mcp.run("stdio", show_banner=False)


if __name__ == "__main__":
    main()
