import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import random

import pytest

from conftest import load_fixture
from yahoo_fantasy_mcp.optimizer.exact_slot import optimize_lineup
from yahoo_fantasy_mcp.yahoo.parsers.league_settings import parse_league_settings

SLOTS = ["QB", "WR", "WR", "RB", "RB", "TE", "W/R", "W/R/T", "K", "DEF"]


def test_slots_come_from_live_league_settings_not_a_hardcoded_list():
    settings = parse_league_settings(load_fixture("league_settings_sample.json"))
    assert settings.starter_slots() == SLOTS


def test_optimizer_fills_duplicate_and_flex_slots_once_each():
    players = [
        {"name": "QB1", "eligible_positions": ["QB"], "projected_points": 24},
        {"name": "WR1", "eligible_positions": ["WR"], "projected_points": 20},
        {"name": "WR2", "eligible_positions": ["WR"], "projected_points": 19},
        {"name": "WR3", "eligible_positions": ["WR"], "projected_points": 18},
        {"name": "WR4", "eligible_positions": ["WR"], "projected_points": 10},
        {"name": "RB1", "eligible_positions": ["RB"], "projected_points": 22},
        {"name": "RB2", "eligible_positions": ["RB"], "projected_points": 21},
        {"name": "RB3", "eligible_positions": ["RB"], "projected_points": 17},
        {"name": "TE1", "eligible_positions": ["TE"], "projected_points": 16},
        {"name": "TE2", "eligible_positions": ["TE"], "projected_points": 9},
        {"name": "K1", "eligible_positions": ["K"], "projected_points": 8},
        {"name": "DEF1", "eligible_positions": ["DST"], "projected_points": 7},
    ]

    result = optimize_lineup(players, SLOTS)
    labels = [row["slot"] for row in result["lineup"]]
    names = [row["player"] for row in result["lineup"]]

    assert result["complete"] is True
    assert labels == ["QB", "WR1", "WR2", "RB1", "RB2", "TE", "W/R", "W/R/T", "K", "DEF"]
    assert len(names) == len(set(names)) == 10
    assert "WR3" in names
    assert "RB3" in names


def test_optimizer_reports_unfillable_slot():
    result = optimize_lineup(
        [{"name": "Only QB", "eligible_positions": ["QB"], "projected_points": 20}], SLOTS
    )
    assert result["complete"] is False
    assert "TE" in result["missing_slots"]
    assert result["warning"]


def test_optimizer_rejects_empty_slots():
    with pytest.raises(ValueError):
        optimize_lineup([{"name": "X", "eligible_positions": ["QB"], "projected_points": 1}], [])


def test_dp_result_matches_independent_hungarian_optimum():
    scipy_opt = pytest.importorskip("scipy.optimize")
    random.seed(7)

    # Guarantee enough depth at every position that a complete lineup (incl.
    # both flex slots) is always fillable -- a pure random.choice() over 18
    # players can easily starve a single-count position like K or DEF.
    quota = {"QB": 2, "WR": 5, "RB": 5, "TE": 3, "K": 2, "DEF": 2}
    players = []
    i = 0
    for pos, count in quota.items():
        for _ in range(count):
            players.append(
                {
                    "name": f"P{i}",
                    "eligible_positions": [pos],
                    "projected_points": round(random.uniform(1, 30), 2),
                }
            )
            i += 1
    random.shuffle(players)

    result = optimize_lineup(players, SLOTS)

    big = 10_000.0
    cost = []
    for player in players:
        row = []
        elig = set(player["eligible_positions"])
        for slot in SLOTS:
            slot_norm = slot.upper()
            ok = (
                slot_norm in elig
                or (slot_norm == "W/R" and elig & {"WR", "RB"})
                or (slot_norm == "W/R/T" and elig & {"WR", "RB", "TE"})
            )
            row.append(-player["projected_points"] if ok else big)
        cost.append(row)

    row_ind, col_ind = scipy_opt.linear_sum_assignment(cost)
    hungarian_total = 0.0
    filled_slots = 0
    for r, c in zip(row_ind, col_ind):
        if cost[r][c] < big:
            hungarian_total += -cost[r][c]
            filled_slots += 1

    assert filled_slots == len(SLOTS)
    assert result["projected_points"] == pytest.approx(round(hungarian_total, 2), abs=0.01)
