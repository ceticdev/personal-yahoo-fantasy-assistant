"""Pure helpers for fitting explosive-play rates from slim NFL play-by-play rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

COUNT_FIELDS = (
    "pass_completions", "passing_40_plus", "passing_40_plus_tds",
    "rush_attempts", "rushing_40_plus", "rushing_40_plus_tds",
    "receptions", "receiving_40_plus", "receiving_40_plus_tds",
)


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _one(value: Any) -> bool:
    return _number(value) == 1.0


def _regular_season(row: Mapping[str, Any]) -> bool:
    season = int(_number(row.get("season")) or 0)
    week = int(_number(row.get("week")) or 0)
    max_week = 17 if season == 2020 else 18
    season_type = str(row.get("season_type", "REG")).upper()
    return season_type == "REG" and 1 <= week <= max_week


def count_row(row: Mapping[str, Any]) -> dict[str, int]:
    """Count eligible pass/run/receiving opportunities and 40+ outcomes in one row."""

    counts = {name: 0 for name in COUNT_FIELDS}
    if not _regular_season(row) or _one(row.get("two_point_attempt")):
        return counts
    play_type = str(row.get("play_type", "")).lower()

    completed = (
        play_type == "pass"
        and _one(row.get("complete_pass"))
        and bool(row.get("passer_player_id"))
        and bool(row.get("receiver_player_id"))
    )
    passing_yards = _number(row.get("passing_yards"))
    receiving_yards = _number(row.get("receiving_yards"))
    if completed and passing_yards is not None:
        counts["pass_completions"] = 1
        if passing_yards >= 40:
            counts["passing_40_plus"] = 1
            counts["passing_40_plus_tds"] = int(_one(row.get("pass_touchdown")))
    if completed and receiving_yards is not None:
        counts["receptions"] = 1
        if receiving_yards >= 40:
            counts["receiving_40_plus"] = 1
            counts["receiving_40_plus_tds"] = int(_one(row.get("pass_touchdown")))

    rushing_yards = _number(row.get("rushing_yards"))
    eligible_run = (
        play_type == "run"
        and bool(row.get("rusher_player_id"))
        and rushing_yards is not None
        and not _one(row.get("qb_kneel"))
        and not _one(row.get("qb_spike"))
    )
    if eligible_run:
        counts["rush_attempts"] = 1
        if rushing_yards >= 40:
            counts["rushing_40_plus"] = 1
            counts["rushing_40_plus_tds"] = int(_one(row.get("rush_touchdown")))
    return counts


def aggregate_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    totals = {name: 0 for name in COUNT_FIELDS}
    for row in rows:
        for name, count in count_row(row).items():
            totals[name] += count
    return totals
