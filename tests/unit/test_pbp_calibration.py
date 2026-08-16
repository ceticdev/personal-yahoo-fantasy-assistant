import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.projections.explosive_play_model import DEFAULT_RATES, load_packaged_rates
from yahoo_fantasy_mcp.projections.pbp_calibration import aggregate_rows, count_row


def _play(**overrides):
    row = {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "play_type": "pass",
        "complete_pass": 1,
        "passer_player_id": "QB",
        "receiver_player_id": "WR",
        "passing_yards": 40,
        "receiving_yards": 40,
        "pass_touchdown": 1,
        "two_point_attempt": 0,
    }
    row.update(overrides)
    return row


def test_pass_and_reception_threshold_counts_both_sides_of_completed_play():
    counts = count_row(_play())
    assert counts["pass_completions"] == 1
    assert counts["passing_40_plus"] == 1
    assert counts["passing_40_plus_tds"] == 1
    assert counts["receptions"] == 1
    assert counts["receiving_40_plus"] == 1


def test_thirty_nine_yards_is_not_explosive():
    counts = count_row(_play(passing_yards=39, receiving_yards=39))
    assert counts["pass_completions"] == 1
    assert counts["passing_40_plus"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"season_type": "POST"},
        {"week": 19},
        {"two_point_attempt": 1},
        {"complete_pass": 0},
        {"passer_player_id": ""},
        {"receiver_player_id": ""},
    ],
)
def test_ineligible_pass_rows_are_excluded(overrides):
    assert sum(count_row(_play(**overrides)).values()) == 0


def test_run_excludes_kneels_and_counts_real_explosive_touchdown():
    run = _play(
        play_type="run", complete_pass=0, passing_yards=None, receiving_yards=None,
        rusher_player_id="RB", rushing_yards=44, rush_touchdown=1,
    )
    counts = count_row(run)
    assert counts["rush_attempts"] == 1
    assert counts["rushing_40_plus_tds"] == 1
    assert aggregate_rows([run, {**run, "qb_kneel": 1}])["rush_attempts"] == 1


def test_packaged_calibration_totals_and_rates_are_self_consistent():
    path = Path(__file__).resolve().parents[2] / "src/yahoo_fantasy_mcp/projections/explosive_play_calibration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    totals = payload["totals"]
    rates = payload["rates"]
    assert rates["completion_40plus_rate"] == pytest.approx(totals["passing_40_plus"] / totals["pass_completions"])
    assert rates["rush_40plus_rate"] == pytest.approx(totals["rushing_40_plus"] / totals["rush_attempts"])
    assert rates["reception_40plus_rate"] == pytest.approx(totals["receiving_40_plus"] / totals["receptions"])
    assert load_packaged_rates() == DEFAULT_RATES
