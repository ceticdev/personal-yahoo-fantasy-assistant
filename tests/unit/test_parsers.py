import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from conftest import load_fixture  # noqa: E402

from yahoo_fantasy_mcp.yahoo.parsers.league_settings import parse_league_settings
from yahoo_fantasy_mcp.yahoo.parsers.players import parse_free_agents
from yahoo_fantasy_mcp.yahoo.parsers.roster import parse_team_roster
from yahoo_fantasy_mcp.yahoo.parsers.transactions import parse_transactions


def test_parse_league_settings():
    settings = parse_league_settings(load_fixture("league_settings_371856.json"))
    assert settings.league_id == "371856"
    assert settings.name == "Katie's Unrivaled League"
    assert settings.num_teams == 6
    assert settings.playoff_start_week == 16
    assert settings.num_playoff_teams == 4
    assert settings.waiver_rule == "continuous"
    assert settings.uses_faab is False

    # Full stat modifier table, not just scoring_type -- this is the gap vs Flaim.
    assert settings.stat_value("5") == 6.0  # passing TD
    assert settings.stat_value("6") == -1.0  # interception
    assert settings.stat_value("78") == 3.0  # 40+ play
    assert settings.stat_value("79") == 2.0  # 40+ play TD bonus
    assert settings.stat_value("999") is None

    slots = settings.starter_slots()
    assert slots == ["QB", "WR", "WR", "RB", "RB", "TE", "W/R", "W/R/T", "K", "DEF"]
    assert "BN" not in slots and "IR" not in slots


def test_parse_team_roster():
    roster = parse_team_roster(load_fixture("roster_team2.json"))
    names = {player.name for player in roster}
    assert names == {"Josh Allen", "Malik Nabers", "Josh Jacobs", "Philadelphia"}

    nabers = next(p for p in roster if p.name == "Malik Nabers")
    assert nabers.status == "Q"
    assert nabers.status_full == "Questionable"
    assert nabers.selected_position == "WR"
    assert nabers.bye_week == 11

    allen = next(p for p in roster if p.name == "Josh Allen")
    assert allen.status is None
    assert allen.selected_position == "QB"


def test_parse_free_agents():
    agents = parse_free_agents(load_fixture("free_agents_sample.json"))
    assert len(agents) == 2
    kittle = next(a for a in agents if a.name == "George Kittle")
    assert kittle.status == "O"
    assert kittle.percent_owned == 41.0
    assert kittle.display_position == "TE"


def test_parse_transactions():
    txs = parse_transactions(load_fixture("transactions_sample.json"))
    assert len(txs) == 1
    tx = txs[0]
    assert tx.transaction_type == "add/drop"
    assert tx.status == "successful"
    assert {move.name for move in tx.players} == {"Bhayshul Tuten", "Jaylen Warren"}
    add_move = next(m for m in tx.players if m.name == "Bhayshul Tuten")
    assert add_move.source_type == "freeagents"
    assert add_move.destination_team_key == "461.l.371856.t.2"
