import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.projections.explosive_play_model import (
    DEFAULT_RATES,
    ExplosivePlayModel,
    fit_from_history,
)


def test_default_model_is_labeled_with_packaged_calibration():
    model = ExplosivePlayModel()
    estimate = model.estimate_receiving(receptions=100)
    assert estimate.basis == "provided_slim_pbp_2020_2025_regular_seasons_v1"
    assert estimate.expected_40_plus == round(100 * DEFAULT_RATES.reception_40plus_rate, 3)


def test_fit_from_history_computes_rates():
    games = [
        {"pass_completions": 20, "passing_40_plus": 1, "passing_40_plus_tds": 1},
        {"pass_completions": 25, "passing_40_plus": 0, "passing_40_plus_tds": 0},
        {"rush_attempts": 15, "rushing_40_plus": 1, "rushing_40_plus_tds": 0},
        {"receptions": 8, "receiving_40_plus": 1, "receiving_40_plus_tds": 1},
    ]
    rates = fit_from_history(games)
    assert rates.completion_40plus_rate == pytest.approx(1 / 45)
    assert rates.rush_40plus_rate == pytest.approx(1 / 15)
    assert rates.reception_40plus_rate == pytest.approx(1 / 8)
    assert rates.td_share_of_40plus == pytest.approx(2 / 3)
    assert rates.basis == "fitted_from_4_historical_game_lines"


def test_fit_from_history_requires_data():
    with pytest.raises(ValueError):
        fit_from_history([])


def test_fit_from_history_rejects_zero_volume_category():
    with pytest.raises(ValueError):
        fit_from_history([{"pass_completions": 0, "rush_attempts": 10, "receptions": 5}])
