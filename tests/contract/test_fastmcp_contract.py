"""Real FastMCP contract coverage using the in-memory `Client` transport.

Every one of the seven registered tools is called through an actual MCP
client/server round trip -- not by calling the Python function directly -- so
schema generation, argument coercion, and result serialization are all
exercised.

The governing assertion across the failure scenarios: **no expected
operational failure surfaces as an uncaught FastMCP ToolError.** Missing
credentials, a missing token, a corrupt token, a failed refresh, Yahoo's
provisioning 403, and a stale-fallback all have to come back as ordinary tool
results carrying a structured error envelope.

`asyncio.run` is used directly so the suite needs no async pytest plugin.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import load_fixture

from yahoo_fantasy_mcp import server as server_module
from yahoo_fantasy_mcp.auth.oauth_client import YahooOAuthClient
from yahoo_fantasy_mcp.auth.token_vault import StoredToken, TokenVault
from yahoo_fantasy_mcp.cache import TTLCache
from yahoo_fantasy_mcp.config import Config
from yahoo_fantasy_mcp.errors import TokenRefreshError, YahooTransportError

TOOL_NAMES = {
    "get_league_settings",
    "get_team_roster",
    "get_free_agents",
    "get_transactions",
    "normalize_projection",
    "optimize_lineup",
    "token_vault_status",
}

LEAGUE_KEY = "999.l.100000"
TEAM_KEY = "999.l.100000.t.1"


# --- harness --------------------------------------------------------------


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Round-trip one tool call through an in-memory MCP client."""

    async def _run():
        async with Client(server_module.mcp) as client:
            result = await client.call_tool(name, arguments or {})
            if getattr(result, "data", None) is not None:
                return result.data
            return json.loads(result.content[0].text)

    return asyncio.run(_run())


def _config(tmp_path: Path, *, credentials: bool = True) -> Config:
    return Config(
        client_id="test-client-id" if credentials else None,
        client_secret="test-client-secret" if credentials else None,
        redirect_uri="oob",
        token_path=tmp_path / "token.json",
        default_league_key=None,
        default_team_key=None,
        cache_ttl_seconds=60,
        log_level="CRITICAL",
        env_file=None,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh server config + cache per test, with no real credentials anywhere."""

    monkeypatch.setattr(server_module, "_config", _config(tmp_path))
    monkeypatch.setattr(server_module, "_cache", TTLCache(ttl_seconds=60))
    monkeypatch.setattr(server_module, "_logger", logging.getLogger("yahoo_fantasy_mcp.test"))
    return tmp_path


def _valid_token() -> StoredToken:
    now = time.time()
    return StoredToken(
        access_token="test-access",
        refresh_token="test-refresh",
        expires_at=now + 3600,
        scope="fspt-r",
        obtained_at=now,
    )


def _vault_a_token(tmp_path: Path, token: StoredToken | None = None) -> None:
    TokenVault(tmp_path / "token.json").save(token or _valid_token())


class _Response:
    """Minimal httpx.Response stand-in for mocked Yahoo replies."""

    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _mock_yahoo(monkeypatch, response=None, *, raises=None):
    def fake_get(url, **kwargs):
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(httpx, "get", fake_get)


def assert_error_envelope(result: dict, *, error_type: str, auth_required=None, retryable=None):
    assert result["data"] is None
    assert result["error_type"] == error_type
    assert isinstance(result["error"], str) and result["error"]
    assert set(result) >= {
        "error",
        "error_type",
        "auth_required",
        "not_provisioned",
        "retryable",
        "data",
    }
    if auth_required is not None:
        assert result["auth_required"] is auth_required
    if retryable is not None:
        assert result["retryable"] is retryable


# --- registration ---------------------------------------------------------


def test_all_seven_tools_are_registered_and_discoverable():
    async def _run():
        async with Client(server_module.mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    assert asyncio.run(_run()) == TOOL_NAMES


def test_every_tool_advertises_a_description():
    async def _run():
        async with Client(server_module.mcp) as client:
            return await client.list_tools()

    for tool in asyncio.run(_run()):
        assert tool.description and tool.description.strip()


# --- pure tools (no Yahoo involved) ---------------------------------------


def test_optimize_lineup_succeeds_over_the_wire(env):
    players = [
        {"name": "QB1", "eligible_positions": ["QB"], "projected_points": 20},
        {"name": "WR1", "eligible_positions": ["WR"], "projected_points": 18},
        {"name": "RB1", "eligible_positions": ["RB"], "projected_points": 17},
    ]
    result = call_tool("optimize_lineup", {"players": players, "slots": ["QB", "WR", "RB"]})

    assert result["complete"] is True
    assert [row["player"] for row in result["lineup"]] == ["QB1", "WR1", "RB1"]


def test_normalize_projection_succeeds_over_the_wire(env):
    result = call_tool(
        "normalize_projection",
        {"stat_line": {"passing_yards": 300.0, "passing_tds": 2.0}, "source": "unit-test"},
    )

    assert result["stat_line"]["passing_yards"] == 300.0
    assert result["estimation_basis"] is None
    assert "passing_40_plus" in result["unavailable_fields"]


def test_invalid_projection_input_returns_a_result_not_a_toolerror(env):
    result = call_tool(
        "normalize_projection",
        {"stat_line": {"not_a_real_stat": 1.0}, "source": "unit-test"},
    )

    assert result["error_type"] == "invalid_input"
    assert result["data"] is None


def test_invalid_optimizer_input_returns_a_result_not_a_toolerror(env):
    result = call_tool(
        "optimize_lineup",
        {"players": [{"name": "X", "eligible_positions": ["QB"], "projected_points": 1}], "slots": []},
    )

    assert result["error_type"] == "invalid_input"
    assert result["data"] is None


# --- mocked successful Yahoo responses ------------------------------------


def test_get_league_settings_with_a_mocked_successful_yahoo_response(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(200, load_fixture("league_settings_sample.json")))

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert result.get("error") is None
    assert result["stale"] is False
    assert result["refresh_failed"] is False
    assert result["data"]["league_id"] == "100000"
    assert result["data"]["starter_slots"] if "starter_slots" in result["data"] else True


def test_get_team_roster_with_a_mocked_successful_yahoo_response(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(200, load_fixture("roster_sample.json")))

    result = call_tool("get_team_roster", {"team_key": TEAM_KEY})

    assert result["stale"] is False
    assert len(result["data"]) == 4
    assert {player["name"] for player in result["data"]} == {
        "Sample Quarterback",
        "Sample Receiver",
        "Sample Runningback",
        "Sample Defense",
    }


def test_get_free_agents_with_a_mocked_successful_yahoo_response(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(200, load_fixture("free_agents_sample.json")))

    result = call_tool("get_free_agents", {"league_key": LEAGUE_KEY, "count": 2})

    assert len(result["data"]) == 2
    assert result["stale"] is False


def test_get_transactions_with_a_mocked_successful_yahoo_response(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(200, load_fixture("transactions_sample.json")))

    result = call_tool("get_transactions", {"league_key": LEAGUE_KEY})

    assert len(result["data"]) == 1
    assert result["data"][0]["transaction_type"] == "add/drop"


# --- failure scenarios, all as structured results -------------------------


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("get_league_settings", {"league_key": LEAGUE_KEY}),
        ("get_team_roster", {"team_key": TEAM_KEY}),
        ("get_free_agents", {"league_key": LEAGUE_KEY}),
        ("get_transactions", {"league_key": LEAGUE_KEY}),
    ],
)
def test_no_credentials_returns_structured_error_for_every_yahoo_tool(tmp_path, monkeypatch, tool, arguments):
    monkeypatch.setattr(server_module, "_config", _config(tmp_path, credentials=False))
    monkeypatch.setattr(server_module, "_cache", TTLCache(ttl_seconds=60))

    result = call_tool(tool, arguments)

    assert_error_envelope(result, error_type="credentials_missing", auth_required=True, retryable=False)


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("get_league_settings", {"league_key": LEAGUE_KEY}),
        ("get_team_roster", {"team_key": TEAM_KEY}),
        ("get_free_agents", {"league_key": LEAGUE_KEY}),
        ("get_transactions", {"league_key": LEAGUE_KEY}),
    ],
)
def test_credentials_but_no_token_returns_structured_error(env, tool, arguments):
    """The original reported bug: this used to escape as an uncaught ToolError."""

    result = call_tool(tool, arguments)

    assert_error_envelope(result, error_type="token_missing", auth_required=True, retryable=False)
    assert "obtain_yahoo_token" in result["error"]


def test_malformed_token_returns_structured_error(env):
    (env / "token.json").write_text('{"unexpected": true}', encoding="utf-8")

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="token_malformed", auth_required=True)


def test_unreadable_token_file_returns_structured_error(env, monkeypatch):
    _vault_a_token(env)

    def deny(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_bytes", deny)

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="token_access_failed", auth_required=True)


def test_refresh_failure_returns_structured_error(env, monkeypatch):
    expired = StoredToken(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=time.time() - 3600,
        scope="fspt-r",
        obtained_at=time.time() - 7200,
    )
    _vault_a_token(env, expired)

    def failing_refresh(self, current):
        raise TokenRefreshError("Yahoo token endpoint returned 400: invalid_grant")

    monkeypatch.setattr(YahooOAuthClient, "refresh", failing_refresh)

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="token_refresh_failed", auth_required=True)


def test_oauth_transport_failure_returns_structured_error(env, monkeypatch):
    expired = StoredToken(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=time.time() - 3600,
        scope="fspt-r",
        obtained_at=time.time() - 7200,
    )
    _vault_a_token(env, expired)

    def unreachable(url, **kwargs):
        raise httpx.ConnectError("name resolution failed")

    monkeypatch.setattr(httpx, "post", unreachable)

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="oauth_transport_failed", retryable=True)


def test_yahoo_401_returns_structured_error(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(401, text="token expired"))

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="yahoo_unauthorized", auth_required=True)


def test_yahoo_provisioning_403_returns_structured_error(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, _Response(403, text="additional_authorization_required"))

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="yahoo_not_provisioned", retryable=False)
    assert result["not_provisioned"] is True
    assert "sports.yahoo.com/developer/access" in result["error"]


def test_yahoo_transport_failure_with_no_cache_returns_structured_error(env, monkeypatch):
    _vault_a_token(env)
    _mock_yahoo(monkeypatch, raises=httpx.ConnectTimeout("timed out"))

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert_error_envelope(result, error_type="yahoo_transport_failed", retryable=True)


# --- stale fallback, end to end through MCP -------------------------------


def test_stale_fallback_surfaces_through_the_mcp_tool(env, monkeypatch):
    """Warm the cache, then break Yahoo: the tool serves labeled stale data."""

    _vault_a_token(env)
    clock_holder = {"now": 1_000_000.0}
    monkeypatch.setattr(
        server_module, "_cache", TTLCache(ttl_seconds=60, clock=lambda: clock_holder["now"])
    )

    _mock_yahoo(monkeypatch, _Response(200, load_fixture("league_settings_sample.json")))
    first = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})
    assert first["stale"] is False
    assert first["refresh_failed"] is False

    clock_holder["now"] += 600  # well past the TTL
    _mock_yahoo(monkeypatch, raises=httpx.ConnectTimeout("yahoo down"))
    second = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    assert second["data"] == first["data"]  # the previous value, preserved
    assert second["stale"] is True
    assert second["age_seconds"] == 600.0
    assert second["refresh_failed"] is True
    assert second["refresh_error"]["error_type"] == "yahoo_transport_failed"
    assert second["refresh_error"]["retryable"] is True


def test_force_refresh_during_an_outage_returns_the_error_not_stale_data(env, monkeypatch):
    _vault_a_token(env)
    clock_holder = {"now": 1_000_000.0}
    monkeypatch.setattr(
        server_module, "_cache", TTLCache(ttl_seconds=60, clock=lambda: clock_holder["now"])
    )

    _mock_yahoo(monkeypatch, _Response(200, load_fixture("league_settings_sample.json")))
    call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    clock_holder["now"] += 600
    _mock_yahoo(monkeypatch, raises=httpx.ConnectTimeout("yahoo down"))
    forced = call_tool("get_league_settings", {"league_key": LEAGUE_KEY, "force_refresh": True})

    assert_error_envelope(forced, error_type="yahoo_transport_failed", retryable=True)


# --- token_vault_status ---------------------------------------------------


def test_token_vault_status_with_no_token(env):
    result = call_tool("token_vault_status")

    assert result["token_present"] is False
    assert result["token"] is None
    assert result["has_credentials_configured"] is True
    assert "protection" in result


def test_token_vault_status_with_a_token_never_returns_raw_values(env):
    _vault_a_token(env)

    result = call_tool("token_vault_status")
    rendered = json.dumps(result)

    assert result["token_present"] is True
    assert result["token"]["access_token"] == "[REDACTED]"
    assert result["token"]["refresh_token"] == "[REDACTED]"
    assert "test-access" not in rendered
    assert "test-refresh" not in rendered


def test_token_vault_status_with_a_corrupt_token_reports_structured_error(env):
    (env / "token.json").write_text("not json at all", encoding="utf-8")

    result = call_tool("token_vault_status")

    assert result["error_type"] == "token_malformed"
    assert result["token_present"] is False


# --- the governing guarantee ----------------------------------------------


def test_no_expected_failure_raises_an_uncaught_toolerror(env, monkeypatch):
    """Sweep every expected failure mode; none may become a ToolError."""

    scenarios = []

    # No credentials.
    scenarios.append(("no credentials", lambda: monkeypatch.setattr(
        server_module, "_config", _config(env, credentials=False))))

    for label, setup in scenarios:
        setup()
        try:
            call_tool("get_league_settings", {"league_key": LEAGUE_KEY})
        except ToolError as exc:  # pragma: no cover - the failure we are guarding against
            pytest.fail(f"{label} raised an uncaught ToolError: {exc}")

    # Restore credentials, then sweep the Yahoo-side failures.
    monkeypatch.setattr(server_module, "_config", _config(env))
    _vault_a_token(env)

    yahoo_failures = [
        ("401", _Response(401, text="expired")),
        ("403 provisioning", _Response(403, text="additional_authorization_required")),
        ("500", _Response(500, text="server error")),
        ("429", _Response(429, text="slow down")),
        ("200 with bad json", _Response(200, payload=None, text="<html>not json</html>")),
    ]
    for label, response in yahoo_failures:
        monkeypatch.setattr(server_module, "_cache", TTLCache(ttl_seconds=60))
        _mock_yahoo(monkeypatch, response)
        try:
            result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})
        except ToolError as exc:  # pragma: no cover
            pytest.fail(f"{label} raised an uncaught ToolError: {exc}")
        assert result["data"] is None
        assert result["error_type"] != "internal_error", f"{label} degraded to internal_error"


def test_a_parser_bug_is_reported_not_disguised_as_stale_data(env, monkeypatch):
    """Programming errors must not be laundered into a friendly stale answer."""

    _vault_a_token(env)
    monkeypatch.setattr(server_module, "_cache", TTLCache(ttl_seconds=60))
    _mock_yahoo(monkeypatch, _Response(200, {"fantasy_content": {"nonsense": True}}))

    result = call_tool("get_league_settings", {"league_key": LEAGUE_KEY})

    # Reported as an internal error, and crucially NOT dressed up as a cache
    # envelope -- there is no `stale` key to mistake for "here is older data".
    assert result["data"] is None
    assert result["error_type"] == "internal_error"
    assert "stale" not in result
    assert result["error"]
    assert result["retryable"] is False
