"""Contract checks for the roster parser against fixture-shaped input."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from conftest import load_fixture
from yahoo_fantasy_mcp.yahoo.parsers.roster import parse_team_roster


def test_missing_team_key_raises():
    with pytest.raises(ValueError):
        parse_team_roster({"fantasy_content": {}})


def test_roster_with_no_roster_section_returns_empty_list_not_a_crash():
    data = {"fantasy_content": {"team": [[{"team_key": "x"}]]}}
    assert parse_team_roster(data) == []


def test_fixture_player_count_matches_expected():
    roster = parse_team_roster(load_fixture("roster_sample.json"))
    assert len(roster) == 4
    assert all(player.name for player in roster)
    assert all(player.eligible_positions for player in roster)
