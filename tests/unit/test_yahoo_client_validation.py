"""Untrusted tool inputs are rejected before OAuth or network access."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.cache import TTLCache
from yahoo_fantasy_mcp.errors import InputValidationError
from yahoo_fantasy_mcp.yahoo.client import YahooFantasyClient


class _NoOAuth:
    def get_valid_token(self):
        raise AssertionError("validation must happen before OAuth")


@pytest.fixture
def client():
    return YahooFantasyClient(_NoOAuth(), TTLCache(60), logging.getLogger("validation-test"))


@pytest.mark.parametrize("key", ["", "123", "123.t.4", "x.l.y/../../bad", "x.l.y t.1"])
def test_invalid_league_keys_fail_closed(client, key):
    with pytest.raises(InputValidationError):
        client.get_league_settings(key)


@pytest.mark.parametrize("key", ["", "123.l.4", "123.l.4.t", "123.l.4.t.1/path"])
def test_invalid_team_keys_fail_closed(client, key):
    with pytest.raises(InputValidationError):
        client.get_team_roster(key)


@pytest.mark.parametrize("count", [True, False, 0, -1, 101, 2.5, "25"])
def test_invalid_counts_fail_closed(client, count):
    with pytest.raises(InputValidationError):
        client.get_transactions("999.l.100000", count=count)


@pytest.mark.parametrize("position", ["", "FLEX", "W/R/T", "QB;count=100"])
def test_invalid_free_agent_positions_fail_closed(client, position):
    with pytest.raises(InputValidationError):
        client.get_free_agents("999.l.100000", position=position)


def test_position_is_normalized_before_path_construction(client, monkeypatch):
    seen = []
    monkeypatch.setattr(client, "_get_json", lambda path: seen.append(path) or {"fantasy_content": {"league": [{}, {"players": {"count": 0}}]}})
    client.get_free_agents("999.l.100000", position=" wr ")
    assert seen == ["league/999.l.100000/players;status=FA;count=25;position=WR"]


@pytest.mark.parametrize("week", [True, False, 0, -3, 1.5, "9"])
def test_invalid_weeks_fail_closed(client, week):
    with pytest.raises(InputValidationError):
        client.get_weekly_matchups("999.l.100000", week=week)
