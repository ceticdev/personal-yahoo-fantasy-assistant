import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.projections.adapter import normalize_stat_line
from yahoo_fantasy_mcp.projections.explosive_play_model import ExplosivePlayModel, fit_from_history


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        normalize_stat_line({"not_a_real_field": 1}, source="test")


def test_missing_40plus_is_labeled_unavailable_by_default():
    result = normalize_stat_line(
        {"receiving_yards": 120, "receptions": 5, "receiving_tds": 1}, source="cbs_projection"
    )
    assert "receiving_40_plus" in result.unavailable_fields
    assert "receiving_40_plus" not in result.stat_line
    assert "unavailable" in result.assumption.lower()


def test_explicit_40plus_counts_are_provided_not_estimated():
    result = normalize_stat_line(
        {
            "receiving_yards": 120,
            "receptions": 5,
            "receiving_tds": 1,
            "receiving_40_plus": 2,
            "receiving_40_plus_tds": 1,
        },
        source="manual",
    )
    assert result.estimated_fields == ()
    assert "receiving_40_plus" in result.provided_fields


def test_opt_in_estimation_fills_and_labels():
    model = ExplosivePlayModel()
    result = normalize_stat_line(
        {"receiving_yards": 120, "receptions": 10, "receiving_tds": 1},
        source="cbs_projection",
        volume={"receptions": 10},
        estimate_explosive_plays=True,
        model=model,
    )
    assert "receiving_40_plus" in result.estimated_fields
    assert "receiving_40_plus" in result.stat_line
    assert "estimate" in result.assumption.lower()


# -- estimation provenance -------------------------------------------------


def test_estimation_basis_is_null_when_nothing_was_estimated():
    result = normalize_stat_line(
        {"receiving_yards": 120, "receptions": 5}, source="cbs_projection"
    )
    assert result.estimation_basis is None
    assert result.as_dict()["estimation_basis"] is None


def test_estimation_basis_reports_the_packaged_calibration():
    """The caller is told exactly which offline calibration supplied the estimate."""

    result = normalize_stat_line(
        {"receiving_yards": 120, "receptions": 10},
        source="cbs_projection",
        volume={"receptions": 10},
        estimate_explosive_plays=True,
        model=ExplosivePlayModel(),
    )

    expected = "provided_slim_pbp_2020_2025_regular_seasons_v1"
    assert result.estimation_basis == expected
    assert result.as_dict()["estimation_basis"] == expected
    assert expected in result.assumption


def test_estimation_basis_reports_a_fitted_model():
    history = [
        {
            "pass_completions": 100,
            "passing_40_plus": 3,
            "passing_40_plus_tds": 1,
            "rush_attempts": 80,
            "rushing_40_plus": 2,
            "rushing_40_plus_tds": 1,
            "receptions": 90,
            "receiving_40_plus": 4,
            "receiving_40_plus_tds": 2,
        }
    ]
    model = ExplosivePlayModel(rates=fit_from_history(history))

    result = normalize_stat_line(
        {"receiving_yards": 120, "receptions": 10},
        source="cbs_projection",
        volume={"receptions": 10},
        estimate_explosive_plays=True,
        model=model,
    )

    assert result.estimation_basis == "fitted_from_1_historical_game_lines"
    assert "unfitted" not in result.estimation_basis


def test_provided_estimated_unavailable_and_zero_remain_distinguishable():
    """A supplied 0 is not the same claim as 'we could not find out'."""

    result = normalize_stat_line(
        {
            "receiving_yards": 120,
            "receptions": 10,
            "rushing_40_plus": 0,  # explicitly zero, and known
            "rushing_40_plus_tds": 0,
        },
        source="mixed",
        volume={"receptions": 10},
        estimate_explosive_plays=True,
        model=ExplosivePlayModel(),
    )
    payload = result.as_dict()

    # Provided (including a real zero).
    assert "rushing_40_plus" in payload["provided_fields"]
    assert "rushing_40_plus" in payload["zero_valued_provided_fields"]
    assert payload["stat_line"]["rushing_40_plus"] == 0.0

    # Estimated.
    assert "receiving_40_plus" in payload["estimated_fields"]

    # Unavailable: never estimated, never provided, and absent from stat_line.
    assert "passing_40_plus" in payload["unavailable_fields"]
    assert "passing_40_plus" not in payload["stat_line"]

    # The four categories do not overlap.
    assert not set(payload["provided_fields"]) & set(payload["estimated_fields"])
    assert not set(payload["estimated_fields"]) & set(payload["unavailable_fields"])
    assert not set(payload["provided_fields"]) & set(payload["unavailable_fields"])
