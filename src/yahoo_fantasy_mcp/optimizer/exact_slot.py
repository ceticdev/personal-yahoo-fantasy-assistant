"""Exact-slot lineup optimization using a small dynamic program.

Ported from `deliverable/matty-fantasy-mcp/fantasy_league_mcp/optimizer.py`
per the deferred-backlog instruction to reuse it here. The one real change:
that version reads `starter_slots` from a hardcoded module-level
`LEAGUE_PROFILE`. This version takes `slots` as an explicit argument, sourced
from `LeagueSettings.starter_slots()` (i.e. Yahoo's live roster-position
table via `get_league_settings`), so the optimizer never drifts out of sync
with the league's actual configured slots.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


ALIASES = {"DST": "DEF", "D/ST": "DEF"}


def _normalize(position: str) -> str:
    value = str(position).strip().upper()
    return ALIASES.get(value, value)


def _eligible(slot: str, positions: set[str]) -> bool:
    slot = _normalize(slot)
    if slot == "W/R":
        return bool(positions & {"WR", "RB"})
    if slot == "W/R/T":
        return bool(positions & {"WR", "RB", "TE"})
    return slot in positions


def optimize_lineup(
    players: Iterable[Mapping[str, Any]], slots: Sequence[str]
) -> dict[str, Any]:
    """Maximize projected points while filling every distinct starter slot.

    Each player needs `name`, `eligible_positions`, and `projected_points`.
    A player can be used once. `slots` is the league's exact starter slot
    list (duplicates repeated, e.g. two `WR` entries for a 2-WR league) --
    pass `LeagueSettings.starter_slots()`, not a hardcoded list, so this
    stays correct if the league's roster settings ever change.
    """

    if not slots:
        raise ValueError("slots is empty -- pass LeagueSettings.starter_slots()")
    if len(slots) > 20:
        # 2**20 masks is already a lot; this is a sanity guard, not a real limit.
        raise ValueError("Refusing to optimize more than 20 starter slots at once")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(players):
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError(f"Player at index {index} is missing a name")
        raw_positions = raw.get("eligible_positions") or raw.get("positions")
        if isinstance(raw_positions, str):
            raw_positions = [part for part in raw_positions.replace(",", "/").split("/") if part]
        if not isinstance(raw_positions, (list, tuple, set)) or not raw_positions:
            raise ValueError(f"{name} needs at least one eligible position")
        try:
            points = float(raw.get("projected_points"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} needs numeric projected_points") from exc
        normalized.append(
            {
                "name": name,
                "eligible_positions": {_normalize(value) for value in raw_positions},
                "projected_points": points,
                "source": raw.get("source", "unspecified"),
                "input_index": index,
            }
        )

    # mask -> (score, assignments); each player updates a snapshot so it is used once.
    dp: dict[int, tuple[float, tuple[tuple[int, int], ...]]] = {0: (0.0, ())}
    for player_index, player in enumerate(normalized):
        next_dp = dict(dp)
        for mask, (score, assignments) in dp.items():
            for slot_index, slot in enumerate(slots):
                bit = 1 << slot_index
                if mask & bit or not _eligible(slot, player["eligible_positions"]):
                    continue
                candidate = score + player["projected_points"]
                new_mask = mask | bit
                incumbent = next_dp.get(new_mask)
                if incumbent is None or candidate > incumbent[0] + 1e-9:
                    next_dp[new_mask] = (candidate, assignments + ((slot_index, player_index),))
        dp = next_dp

    best_mask, (best_score, assignments) = max(
        dp.items(), key=lambda item: (item[0].bit_count(), item[1][0])
    )
    counts: dict[str, int] = {}
    lineup: list[dict[str, Any]] = []
    selected: set[int] = set()
    for slot_index, player_index in sorted(assignments):
        slot = slots[slot_index]
        counts[slot] = counts.get(slot, 0) + 1
        label = f"{slot}{counts[slot]}" if slots.count(slot) > 1 else slot
        player = normalized[player_index]
        selected.add(player_index)
        lineup.append(
            {
                "slot": label,
                "player": player["name"],
                "projected_points": round(player["projected_points"], 2),
                "source": player["source"],
            }
        )

    bench = [
        {
            "player": player["name"],
            "projected_points": round(player["projected_points"], 2),
            "source": player["source"],
        }
        for index, player in enumerate(normalized)
        if index not in selected
    ]
    bench.sort(key=lambda row: row["projected_points"], reverse=True)
    missing = [slots[index] for index in range(len(slots)) if not best_mask & (1 << index)]

    return {
        "complete": not missing,
        "projected_points": round(best_score, 2),
        "lineup": lineup,
        "bench": bench,
        "missing_slots": missing,
        "warning": None if not missing else "Roster input cannot fill every required starter slot.",
    }
