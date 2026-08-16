"""Read-only enforcement at the transport layer.

`test_no_write_tools.py` proves no tool is *named* like a write. That is worth
keeping, but on its own it proves nothing about what goes over the wire -- a
tool called `get_roster` could still issue a PUT. These tests close that gap
by asserting the actual HTTP behavior and the source-level absence of any
write path:

* every Yahoo Fantasy data request uses GET, and only GET;
* no PUT/PATCH/DELETE is issued anywhere, and no roster-write, transaction-
  write, or lineup-submit endpoint appears in the source;
* the single POST in the package goes to Yahoo's exact OAuth token endpoint
  and nowhere else;
* the requested OAuth scope is exactly `fspt-r`, with no write scope anywhere.
"""

import ast
import inspect
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import httpx
import pytest

from conftest import load_fixture

from yahoo_fantasy_mcp import server as server_module
from yahoo_fantasy_mcp.auth import oauth_client as oauth_module
from yahoo_fantasy_mcp.auth.oauth_client import TOKEN_URL, YahooOAuthClient
from yahoo_fantasy_mcp.auth.token_vault import StoredToken
from yahoo_fantasy_mcp.cache import TTLCache
from yahoo_fantasy_mcp.config import READ_ONLY_SCOPE
from yahoo_fantasy_mcp.yahoo import client as yahoo_client_module
from yahoo_fantasy_mcp.yahoo.client import BASE_URL, YahooFantasyClient

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
SOURCE_FILES = sorted(SRC_ROOT.rglob("*.py"))

WRITE_METHODS = ("put", "patch", "delete", "post")


class _StubOAuth:
    """Supplies a token without touching the network."""

    scope = READ_ONLY_SCOPE

    def get_valid_token(self):
        now = time.time()
        return StoredToken("a", "r", now + 3600, READ_ONLY_SCOPE, now)


def _client(monkeypatch, recorder):
    monkeypatch.setattr(httpx, "get", recorder)
    for method in WRITE_METHODS:
        monkeypatch.setattr(
            httpx,
            method,
            _forbid(method),
        )
    import logging

    return YahooFantasyClient(
        oauth_client=_StubOAuth(), cache=TTLCache(ttl_seconds=60), logger=logging.getLogger("test")
    )


def code_string_literals(path: Path) -> list[str]:
    """Every string literal in a module that is NOT a docstring.

    Documentation is allowed to *discuss* write scope and write endpoints --
    saying "this client never requests fspt-w" is the point. What must not
    exist is an actual code literal that could be sent to Yahoo.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def _forbid(method_name):
    def _fail(*args, **kwargs):
        raise AssertionError(f"httpx.{method_name}() must never be called on a read path")

    return _fail


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = "{}"

    def json(self):
        return self._payload


# --- runtime behavior -----------------------------------------------------


@pytest.mark.parametrize(
    "call,fixture",
    [
        (lambda c: c.get_league_settings("999.l.100000"), "league_settings_sample.json"),
        (lambda c: c.get_team_roster("999.l.100000.t.1"), "roster_sample.json"),
        (lambda c: c.get_free_agents("999.l.100000"), "free_agents_sample.json"),
        (lambda c: c.get_transactions("999.l.100000"), "transactions_sample.json"),
        (lambda c: c.get_league_standings("999.l.100000"), "standings_sample.json"),
        (lambda c: c.get_weekly_matchups("999.l.100000", week=9), "matchups_sample.json"),
    ],
)
def test_every_yahoo_data_request_uses_get_only(monkeypatch, call, fixture):
    seen = []

    def record_get(url, **kwargs):
        seen.append(url)
        return _Response(load_fixture(fixture))

    call(_client(monkeypatch, record_get))

    # httpx.put/patch/delete/post are all booby-trapped above; reaching here
    # means only httpx.get was used.
    assert len(seen) == 1
    assert seen[0].startswith(BASE_URL)


def test_read_path_never_touches_a_write_verb(monkeypatch):
    """Belt and braces: the whole read surface, with write verbs sabotaged."""

    def record_get(url, **kwargs):
        return _Response(load_fixture("league_settings_sample.json"))

    client = _client(monkeypatch, record_get)
    client.get_league_settings("999.l.100000")
    client.get_league_settings("999.l.100000", force_refresh=True)


def test_oauth_post_targets_only_yahoos_exact_token_endpoint(monkeypatch, tmp_path):
    posted = []

    def record_post(url, **kwargs):
        posted.append(url)

        class _TokenResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                }

        return _TokenResponse()

    monkeypatch.setattr(httpx, "post", record_post)

    from yahoo_fantasy_mcp.auth.token_vault import TokenVault

    client = YahooOAuthClient(
        client_id="id",
        client_secret="secret",
        redirect_uri="oob",
        vault=TokenVault(tmp_path / "token.json"),
    )
    client.refresh(StoredToken("a", "r", time.time() - 10, READ_ONLY_SCOPE, time.time()))

    assert posted == [TOKEN_URL]
    assert TOKEN_URL == "https://api.login.yahoo.com/oauth2/get_token"


def test_requested_scope_is_exactly_read_only(tmp_path):
    from yahoo_fantasy_mcp.auth.token_vault import TokenVault

    client = YahooOAuthClient(
        client_id="id",
        client_secret="secret",
        redirect_uri="oob",
        vault=TokenVault(tmp_path / "token.json"),
    )

    assert client.scope == "fspt-r"
    assert READ_ONLY_SCOPE == "fspt-r"
    assert "scope=fspt-r" in client.authorization_url()
    assert "fspt-w" not in client.authorization_url()


# --- source-level absence of any write path -------------------------------


def test_no_write_verb_http_call_exists_in_the_yahoo_data_client():
    source = inspect.getsource(yahoo_client_module)

    for method in ("put", "patch", "delete", "post"):
        assert f"httpx.{method}(" not in source, f"yahoo/client.py must not call httpx.{method}()"
    assert "httpx.get(" in source


def test_the_only_post_in_the_package_is_the_oauth_token_exchange():
    offenders = []
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        for method in ("put", "patch", "delete", "post"):
            if f"httpx.{method}(" in text:
                offenders.append((path.name, method))

    assert offenders == [("oauth_client.py", "post")], f"unexpected write-verb calls: {offenders}"


def test_no_write_endpoint_paths_appear_anywhere_in_the_source():
    """Yahoo's write resources are simply absent from this codebase."""

    # Note: `league/{key}/transactions` is BOTH the read collection and the
    # add/drop write endpoint -- they differ only by HTTP method, so the
    # protection there is the GET-only assertions above, not the path string.
    # What can be excluded by path is the lineup-change resource, which the
    # read surface has no reason to name at all.
    forbidden = ("roster/players",)  # PUT /team/{key}/roster changes a lineup
    for path in SOURCE_FILES:
        for literal in code_string_literals(path):
            for needle in forbidden:
                assert needle not in literal, f"{path.name} references a write path: {needle}"


def test_no_write_scope_literal_exists_in_the_source():
    """Docstrings may explain fspt-w; no code literal may ever contain it."""

    for path in SOURCE_FILES:
        for literal in code_string_literals(path):
            assert "fspt-w" not in literal, f"{path.name} contains an fspt-w code literal"


def test_server_exposes_no_tool_that_mutates_yahoo_state():
    """The registered surface is read/compute only, checked by signature intent."""

    source = inspect.getsource(server_module)
    # No tool body may construct a non-GET request.
    for method in ("httpx.put", "httpx.post", "httpx.patch", "httpx.delete"):
        assert method not in source


def test_yahoo_request_paths_are_all_read_resources():
    """Every path template the client builds is a documented read resource."""

    source = inspect.getsource(yahoo_client_module)
    paths = re.findall(r'_get_json\(\s*f?"([^"]+)"', source)

    assert paths, "expected to find the client's Yahoo resource paths"
    for path in paths:
        assert any(
            path.startswith(prefix) for prefix in ("league/", "team/")
        ), f"unexpected resource root: {path}"
        assert path.endswith(("settings", "roster", "standings")) or any(
            segment in path for segment in ("players", "transactions", "scoreboard")
        )
