import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.projections.adapter import normalize_stat_line
from yahoo_fantasy_mcp.projections.explosive_play_model import ExplosivePlayModel


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
