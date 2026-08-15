"""Contract checks: fails loudly if Yahoo's JSON shape assumption breaks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from conftest import load_fixture
from yahoo_fantasy_mcp.yahoo.parsers.league_settings import parse_league_settings


def test_fixture_round_trip_is_stable():
    settings = parse_league_settings(load_fixture("league_settings_sample.json"))
    # Re-serializing and re-parsing the same shape should be a no-op --
    # guards against accidental mutation of shared fixture data.
    settings_again = parse_league_settings(load_fixture("league_settings_sample.json"))
    assert settings == settings_again


def test_missing_settings_key_raises_not_silently_empty():
    broken = {"fantasy_content": {"league": [{"league_key": "x"}, {}]}}
    with pytest.raises(ValueError):
        parse_league_settings(broken)


def test_missing_league_key_raises():
    with pytest.raises(ValueError):
        parse_league_settings({"fantasy_content": {}})


def test_empty_roster_positions_list_yields_empty_slots_not_a_crash():
    minimal = {
        "fantasy_content": {
            "league": [
                {"league_key": "x", "league_id": "1", "name": "n", "season": "2026", "num_teams": 2},
                {"settings": [{"scoring_type": "head", "roster_positions": []}]},
            ]
        }
    }
    settings = parse_league_settings(minimal)
    assert settings.starter_slots() == []
    assert settings.stat_modifiers == []
