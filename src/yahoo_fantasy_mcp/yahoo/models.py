"""Typed models for Yahoo Fantasy Sports API data.

A typical hosted connector returns only the general scoring type (e.g. "head" /
points format) but not the full stat-modifier table, which is the piece the
custom scoring engine actually needs to cross-check against Yahoo's own
config. These models exist to carry that full table plus the exact roster
position counts, typed instead of passed around as raw dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StatModifier:
    stat_id: str
    name: str
    value: float


@dataclass(frozen=True, slots=True)
class RosterPosition:
    position: str
    position_type: str | None  # "O" offense / "D" defense / "K" / None
    count: int
    is_bench: bool = False


@dataclass(frozen=True, slots=True)
class LeagueSettings:
    league_key: str
    league_id: str
    name: str
    season: str
    num_teams: int
    scoring_type: str
    uses_faab: bool
    waiver_rule: str
    playoff_start_week: int | None
    num_playoff_teams: int | None
    stat_modifiers: list[StatModifier] = field(default_factory=list)
    roster_positions: list[RosterPosition] = field(default_factory=list)

    def stat_value(self, stat_id: str) -> float | None:
        for modifier in self.stat_modifiers:
            if modifier.stat_id == stat_id:
                return modifier.value
        return None

    def starter_slots(self) -> list[str]:
        """Flat list of starter slot labels, e.g. ["QB","WR","WR","RB", ...].

        This is what the optimizer needs -- one entry per starter slot,
        duplicated positions repeated, bench/IR excluded.
        """

        slots: list[str] = []
        for position in self.roster_positions:
            if position.is_bench or position.position in {"BN", "IR"}:
                continue
            slots.extend([position.position] * position.count)
        return slots


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    player_key: str
    player_id: str
    name: str
    editorial_team_abbr: str | None
    display_position: str
    eligible_positions: list[str]
    selected_position: str | None
    status: str | None  # Yahoo short status code, e.g. "Q", "O", "IR"
    status_full: str | None  # Yahoo's longer status description
    bye_week: int | None


@dataclass(frozen=True, slots=True)
class FreeAgentPlayer:
    player_key: str
    player_id: str
    name: str
    editorial_team_abbr: str | None
    display_position: str
    eligible_positions: list[str]
    status: str | None
    status_full: str | None
    percent_owned: float | None
    bye_week: int | None


@dataclass(frozen=True, slots=True)
class TransactionPlayerMove:
    player_key: str
    name: str
    source_type: str  # "freeagents", "waivers", "team"
    destination_type: str  # "team", "freeagents", "waivers"
    source_team_key: str | None
    destination_team_key: str | None


@dataclass(frozen=True, slots=True)
class Transaction:
    transaction_key: str
    transaction_type: str  # "add", "drop", "add/drop", "trade"
    status: str
    timestamp: int  # unix epoch seconds, as Yahoo returns it
    players: list[TransactionPlayerMove] = field(default_factory=list)
