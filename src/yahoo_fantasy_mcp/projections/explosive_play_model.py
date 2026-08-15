"""Historical rate model for expected 40+ yard plays and long touchdowns.

Yahoo season-total projections do not carry 40+ play counts, so the
optimizer's output is a slot-assignment check, not a fully custom-scored
projection. This module exists to close that gap -- but honestly: the default
rates below are **placeholders**, not a fit to real play-by-play data. No
historical play-by-play or box-score dataset was available to fit against in
this build. Call `fit_from_history()` with real season data before
trusting this in a live decision; until then, every estimate this module
returns is labeled with `basis` so it can never be mistaken for a measured
rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ExplosivePlayRates:
    completion_40plus_rate: float  # 40+ pass plays per completion
    rush_40plus_rate: float  # 40+ runs per rush attempt
    reception_40plus_rate: float  # 40+ receptions per reception
    td_share_of_40plus: float  # fraction of 40+ plays that are also touchdowns
    basis: str


# Deliberately conservative, round placeholder rates. NOT measured. See
# module docstring. Replace by calling `fit_from_history()` with real
# season data and passing the result into ExplosivePlayModel.
DEFAULT_RATES = ExplosivePlayRates(
    completion_40plus_rate=0.02,
    rush_40plus_rate=0.015,
    reception_40plus_rate=0.018,
    td_share_of_40plus=0.35,
    basis="unfitted_default_placeholder",
)


def fit_from_history(games: Iterable[Mapping[str, Any]]) -> ExplosivePlayRates:
    """Fit rates from historical game lines with real 40+ counts.

    Each `games` entry may supply any subset of:
      pass_completions, passing_40_plus, passing_40_plus_tds,
      rush_attempts, rushing_40_plus, rushing_40_plus_tds,
      receptions, receiving_40_plus, receiving_40_plus_tds

    Raises ValueError if there isn't enough volume in any one category to
    produce a rate -- silently returning a 0.0 rate from a near-empty sample
    would look like a real fit and is worse than failing loudly.
    """

    totals = {
        "pass_completions": 0.0,
        "passing_40_plus": 0.0,
        "passing_40_plus_tds": 0.0,
        "rush_attempts": 0.0,
        "rushing_40_plus": 0.0,
        "rushing_40_plus_tds": 0.0,
        "receptions": 0.0,
        "receiving_40_plus": 0.0,
        "receiving_40_plus_tds": 0.0,
    }
    game_count = 0
    for game in games:
        game_count += 1
        for key in totals:
            totals[key] += float(game.get(key, 0) or 0)

    if game_count == 0:
        raise ValueError("fit_from_history() needs at least one historical game line")

    def _rate(count_key: str, volume_key: str) -> float:
        volume = totals[volume_key]
        if volume <= 0:
            raise ValueError(
                f"Cannot fit a rate for {count_key}: zero {volume_key} in the supplied history"
            )
        return totals[count_key] / volume

    total_40plus = totals["passing_40_plus"] + totals["rushing_40_plus"] + totals["receiving_40_plus"]
    total_40plus_tds = (
        totals["passing_40_plus_tds"] + totals["rushing_40_plus_tds"] + totals["receiving_40_plus_tds"]
    )
    td_share = (total_40plus_tds / total_40plus) if total_40plus > 0 else DEFAULT_RATES.td_share_of_40plus

    return ExplosivePlayRates(
        completion_40plus_rate=_rate("passing_40_plus", "pass_completions"),
        rush_40plus_rate=_rate("rushing_40_plus", "rush_attempts"),
        reception_40plus_rate=_rate("receiving_40_plus", "receptions"),
        td_share_of_40plus=td_share,
        basis=f"fitted_from_{game_count}_historical_game_lines",
    )


@dataclass(frozen=True, slots=True)
class ExplosivePlayEstimate:
    expected_40_plus: float
    expected_40_plus_tds: float
    basis: str


class ExplosivePlayModel:
    def __init__(self, rates: ExplosivePlayRates = DEFAULT_RATES) -> None:
        self.rates = rates

    def estimate_passing(self, pass_completions: float) -> ExplosivePlayEstimate:
        expected = pass_completions * self.rates.completion_40plus_rate
        return ExplosivePlayEstimate(
            expected_40_plus=round(expected, 3),
            expected_40_plus_tds=round(expected * self.rates.td_share_of_40plus, 3),
            basis=self.rates.basis,
        )

    def estimate_rushing(self, rush_attempts: float) -> ExplosivePlayEstimate:
        expected = rush_attempts * self.rates.rush_40plus_rate
        return ExplosivePlayEstimate(
            expected_40_plus=round(expected, 3),
            expected_40_plus_tds=round(expected * self.rates.td_share_of_40plus, 3),
            basis=self.rates.basis,
        )

    def estimate_receiving(self, receptions: float) -> ExplosivePlayEstimate:
        expected = receptions * self.rates.reception_40plus_rate
        return ExplosivePlayEstimate(
            expected_40_plus=round(expected, 3),
            expected_40_plus_tds=round(expected * self.rates.td_share_of_40plus, 3),
            basis=self.rates.basis,
        )
