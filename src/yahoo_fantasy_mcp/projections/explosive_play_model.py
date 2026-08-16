"""Calibrated rate model for expected 40+ yard plays and long touchdowns.

The packaged default is a reproducible offline fit over the supplied slim
2020-2025 regular-season play-by-play files. It is still an estimate—not an
observed Yahoo projection—so every returned estimate carries its basis label.
The artifact loads fail-closed: missing or malformed data never degrades to
invented rates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ExplosivePlayRates:
    completion_40plus_rate: float
    rush_40plus_rate: float
    reception_40plus_rate: float
    td_share_of_40plus: float
    basis: str
    passing_td_share_of_40plus: float | None = None
    rushing_td_share_of_40plus: float | None = None
    receiving_td_share_of_40plus: float | None = None


def _rate(name: str, value: Any) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"Calibration rate {name} must be between 0 and 1")
    return result


def load_packaged_rates() -> ExplosivePlayRates:
    """Load and validate the versioned calibration bundled with the package."""

    resource = files(__package__).joinpath("explosive_play_calibration.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    rates = payload.get("rates")
    basis = payload.get("basis")
    if not isinstance(rates, dict) or not isinstance(basis, str) or not basis.strip():
        raise ValueError("Explosive-play calibration is missing rates or basis")
    required = (
        "completion_40plus_rate",
        "rush_40plus_rate",
        "reception_40plus_rate",
        "td_share_of_40plus",
        "passing_td_share_of_40plus",
        "rushing_td_share_of_40plus",
        "receiving_td_share_of_40plus",
    )
    missing = [name for name in required if name not in rates]
    if missing:
        raise ValueError(f"Explosive-play calibration is missing: {', '.join(missing)}")
    return ExplosivePlayRates(
        completion_40plus_rate=_rate("completion_40plus_rate", rates["completion_40plus_rate"]),
        rush_40plus_rate=_rate("rush_40plus_rate", rates["rush_40plus_rate"]),
        reception_40plus_rate=_rate("reception_40plus_rate", rates["reception_40plus_rate"]),
        td_share_of_40plus=_rate("td_share_of_40plus", rates["td_share_of_40plus"]),
        basis=basis,
        passing_td_share_of_40plus=_rate(
            "passing_td_share_of_40plus", rates["passing_td_share_of_40plus"]
        ),
        rushing_td_share_of_40plus=_rate(
            "rushing_td_share_of_40plus", rates["rushing_td_share_of_40plus"]
        ),
        receiving_td_share_of_40plus=_rate(
            "receiving_td_share_of_40plus", rates["receiving_td_share_of_40plus"]
        ),
    )


DEFAULT_RATES = load_packaged_rates()


def fit_from_history(games: Iterable[Mapping[str, Any]]) -> ExplosivePlayRates:
    """Fit category rates from historical lines containing real 40+ counts."""

    keys = (
        "pass_completions", "passing_40_plus", "passing_40_plus_tds",
        "rush_attempts", "rushing_40_plus", "rushing_40_plus_tds",
        "receptions", "receiving_40_plus", "receiving_40_plus_tds",
    )
    totals = {key: 0.0 for key in keys}
    game_count = 0
    for game in games:
        game_count += 1
        for key in totals:
            totals[key] += float(game.get(key, 0) or 0)
    if game_count == 0:
        raise ValueError("fit_from_history() needs at least one historical game line")

    def ratio(numerator: str, denominator: str) -> float:
        if totals[denominator] <= 0:
            raise ValueError(
                f"Cannot fit a rate for {numerator}: zero {denominator} in supplied history"
            )
        return totals[numerator] / totals[denominator]

    passing_share = ratio("passing_40_plus_tds", "passing_40_plus")
    rushing_share = ratio("rushing_40_plus_tds", "rushing_40_plus")
    receiving_share = ratio("receiving_40_plus_tds", "receiving_40_plus")
    total_explosive = sum(
        totals[key] for key in ("passing_40_plus", "rushing_40_plus", "receiving_40_plus")
    )
    total_tds = sum(
        totals[key]
        for key in ("passing_40_plus_tds", "rushing_40_plus_tds", "receiving_40_plus_tds")
    )
    return ExplosivePlayRates(
        completion_40plus_rate=ratio("passing_40_plus", "pass_completions"),
        rush_40plus_rate=ratio("rushing_40_plus", "rush_attempts"),
        reception_40plus_rate=ratio("receiving_40_plus", "receptions"),
        td_share_of_40plus=total_tds / total_explosive,
        basis=f"fitted_from_{game_count}_historical_game_lines",
        passing_td_share_of_40plus=passing_share,
        rushing_td_share_of_40plus=rushing_share,
        receiving_td_share_of_40plus=receiving_share,
    )


@dataclass(frozen=True, slots=True)
class ExplosivePlayEstimate:
    expected_40_plus: float
    expected_40_plus_tds: float
    basis: str


class ExplosivePlayModel:
    def __init__(self, rates: ExplosivePlayRates = DEFAULT_RATES) -> None:
        self.rates = rates

    def _estimate(self, volume: float, rate: float, td_share: float | None) -> ExplosivePlayEstimate:
        expected = volume * rate
        share = self.rates.td_share_of_40plus if td_share is None else td_share
        return ExplosivePlayEstimate(round(expected, 3), round(expected * share, 3), self.rates.basis)

    def estimate_passing(self, pass_completions: float) -> ExplosivePlayEstimate:
        return self._estimate(
            pass_completions,
            self.rates.completion_40plus_rate,
            self.rates.passing_td_share_of_40plus,
        )

    def estimate_rushing(self, rush_attempts: float) -> ExplosivePlayEstimate:
        return self._estimate(
            rush_attempts,
            self.rates.rush_40plus_rate,
            self.rates.rushing_td_share_of_40plus,
        )

    def estimate_receiving(self, receptions: float) -> ExplosivePlayEstimate:
        return self._estimate(
            receptions,
            self.rates.reception_40plus_rate,
            self.rates.receiving_td_share_of_40plus,
        )
