"""Normalize raw stat distributions from any projection source into one shape.

This module does NOT score points. Scoring stays owned by the separate
Matty Fantasy MCP (`get_league_profile` / `score_player_stat_line`), which is
the deterministic custom-scoring engine in this setup. What this adapter does:

1. Accepts a raw stat line from any source (Yahoo, CBS, a manual estimate)
   using the field names the scoring engine expects
   (`OffensiveStatLine` in matty-fantasy-mcp).
2. Never silently invents a 40+ play count. If the caller wants an estimate,
   they must opt in by passing `volume` and `estimate_explosive_plays=True` --
   the acceptance gate in the plan is that the assistant "explicitly says
   when 40+ play counts were unavailable rather than manufacturing an
   adjustment," so estimation is opt-in and every estimated field is labeled.
3. Stamps every normalized line with a source label and an as-of timestamp,
   so a stale projection can never masquerade as a fresh one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .explosive_play_model import ExplosivePlayModel

# Field names must match matty-fantasy-mcp's OffensiveStatLine exactly so the
# output of this adapter can be passed straight to score_player_stat_line.
STAT_LINE_FIELDS = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_two_point",
    "passing_40_plus",
    "passing_40_plus_tds",
    "rushing_yards",
    "rushing_tds",
    "rushing_two_point",
    "rushing_40_plus",
    "rushing_40_plus_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_two_point",
    "receiving_40_plus",
    "receiving_40_plus_tds",
    "fumbles_lost",
    "external_points",
)

_EXPLOSIVE_FIELD_SOURCE = {
    "passing_40_plus": ("passing", "pass_completions"),
    "passing_40_plus_tds": ("passing", "pass_completions"),
    "rushing_40_plus": ("rushing", "rush_attempts"),
    "rushing_40_plus_tds": ("rushing", "rush_attempts"),
    "receiving_40_plus": ("receiving", "receptions"),
    "receiving_40_plus_tds": ("receiving", "receptions"),
}


@dataclass(frozen=True, slots=True)
class NormalizedStatLine:
    stat_line: dict[str, float]
    source: str
    as_of: float
    provided_fields: tuple[str, ...]
    estimated_fields: tuple[str, ...]
    unavailable_fields: tuple[str, ...]
    assumption: str
    #: Provenance of any estimated value: the explosive-play model's `basis`
    #: (the packaged PBP calibration label, or a `fitted_from_N_...` label for
    #: caller-supplied rates). None when nothing was estimated.
    estimation_basis: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "stat_line": self.stat_line,
            "source": self.source,
            "as_of": self.as_of,
            "provided_fields": list(self.provided_fields),
            "estimated_fields": list(self.estimated_fields),
            "unavailable_fields": list(self.unavailable_fields),
            "zero_valued_provided_fields": [
                name for name in self.provided_fields if float(self.stat_line.get(name, 0.0)) == 0.0
            ],
            "assumption": self.assumption,
            "estimation_basis": self.estimation_basis,
        }


def normalize_stat_line(
    raw: Mapping[str, Any],
    *,
    source: str,
    as_of: float | None = None,
    volume: Mapping[str, float] | None = None,
    estimate_explosive_plays: bool = False,
    model: ExplosivePlayModel | None = None,
) -> NormalizedStatLine:
    unknown = sorted(set(raw) - set(STAT_LINE_FIELDS))
    if unknown:
        raise ValueError(f"Unknown stat fields for this source: {', '.join(unknown)}")

    provided = {key for key in raw if key in STAT_LINE_FIELDS}
    line: dict[str, float] = {key: float(raw[key]) for key in provided}
    estimated: set[str] = set()
    unavailable: set[str] = set()
    estimation_bases: set[str] = set()

    for total_field, td_field in (
        ("passing_40_plus", "passing_40_plus_tds"),
        ("rushing_40_plus", "rushing_40_plus_tds"),
        ("receiving_40_plus", "receiving_40_plus_tds"),
    ):
        if total_field in provided or td_field in provided:
            continue  # caller already supplied real data for this category

        if estimate_explosive_plays and volume is not None:
            category, volume_key = _EXPLOSIVE_FIELD_SOURCE[total_field]
            volume_value = volume.get(volume_key)
            if volume_value is not None and model is not None:
                estimate = {
                    "passing": model.estimate_passing,
                    "rushing": model.estimate_rushing,
                    "receiving": model.estimate_receiving,
                }[category](float(volume_value))
                line[total_field] = estimate.expected_40_plus
                line[td_field] = estimate.expected_40_plus_tds
                estimated.add(total_field)
                estimated.add(td_field)
                # Carry the model's provenance out to the caller rather than
                # telling them to inspect a `basis` field we then discard.
                estimation_bases.add(estimate.basis)
                continue

        unavailable.add(total_field)
        unavailable.add(td_field)

    # A call can be partly estimated and partly unavailable at once (volume
    # supplied for one category but not another), so the assumption reports
    # every state that actually applies rather than only the first one.
    parts: list[str] = []
    if unavailable:
        parts.append(
            "40+ play counts unavailable for: "
            f"{', '.join(sorted(unavailable))}. Treated as zero for scoring; "
            "this understates true points for any player with real explosive "
            "plays. Supply raw counts or opt into estimate_explosive_plays "
            "with volume stats to close this gap."
        )
    if estimated:
        parts.append(
            f"40+ play counts for {', '.join(sorted(estimated))} are model "
            f"estimates, not observed counts. Basis: "
            f"{', '.join(sorted(estimation_bases)) or 'unknown'}."
        )
    if not parts:
        parts.append("All 40+ play fields were supplied directly by the source.")
    assumption = " ".join(parts)

    return NormalizedStatLine(
        stat_line=line,
        source=source,
        as_of=as_of if as_of is not None else time.time(),
        provided_fields=tuple(sorted(provided)),
        estimated_fields=tuple(sorted(estimated)),
        unavailable_fields=tuple(sorted(unavailable)),
        assumption=assumption,
        estimation_basis=(
            # Deterministic and singular in practice: one model supplies every
            # estimate in a call. Joined defensively if that ever changes.
            ", ".join(sorted(estimation_bases)) if estimation_bases else None
        ),
    )
