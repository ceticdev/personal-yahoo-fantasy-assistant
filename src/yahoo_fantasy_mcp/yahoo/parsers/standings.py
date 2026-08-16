"""Parse Yahoo league standings responses into typed records."""

from __future__ import annotations

from typing import Any

from ..models import TeamStanding
from ._common import as_float, as_int, flatten_element_list, iter_indexed


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _league(data: dict[str, Any]) -> list[Any]:
    league = data.get("fantasy_content", {}).get("league")
    if not isinstance(league, list):
        raise ValueError("Response is missing fantasy_content.league")
    return league


def _teams_container(league: list[Any]) -> dict[str, Any]:
    for item in league[1:]:
        if not isinstance(item, dict):
            continue
        standings = item.get("standings")
        candidates = standings if isinstance(standings, list) else [standings]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            teams = candidate.get("teams")
            if isinstance(teams, dict):
                return teams
    raise ValueError("Response is missing league standings teams")


def parse_league_standings(data: dict[str, Any]) -> list[TeamStanding]:
    """Return all standings rows, preserving rank and tiebreak details."""

    teams = _teams_container(_league(data))
    if as_int(teams.get("count"), default=None) == 0:
        return []

    result: list[TeamStanding] = []
    for entry in iter_indexed(teams):
        raw_team = entry.get("team") if isinstance(entry, dict) else None
        if not isinstance(raw_team, list) or not raw_team:
            continue
        identity = flatten_element_list(raw_team[0])
        standing: dict[str, Any] | None = None
        points: dict[str, Any] = {}
        for part in raw_team[1:]:
            if not isinstance(part, dict):
                continue
            candidate = part.get("team_standings")
            if isinstance(candidate, dict):
                standing = candidate
            candidate_points = part.get("team_points")
            if isinstance(candidate_points, dict):
                points = candidate_points
        if standing is None:
            raise ValueError("A standings team is missing team_standings")

        totals = standing.get("outcome_totals")
        totals = totals if isinstance(totals, dict) else {}
        streak = standing.get("streak")
        streak = streak if isinstance(streak, dict) else {}
        points_for = as_float(standing.get("points_for"))
        if points_for is None:
            points_for = as_float(points.get("total"))
        result.append(
            TeamStanding(
                team_key=str(identity.get("team_key", "")),
                team_id=str(identity.get("team_id", "")),
                name=str(identity.get("name", "")),
                rank=as_int(standing.get("rank"), default=0) or 0,
                wins=as_int(totals.get("wins"), default=0) or 0,
                losses=as_int(totals.get("losses"), default=0) or 0,
                ties=as_int(totals.get("ties"), default=0) or 0,
                percentage=as_float(totals.get("percentage")),
                points_for=points_for,
                points_against=as_float(standing.get("points_against")),
                games_back=as_float(standing.get("games_back")),
                playoff_seed=as_int(standing.get("playoff_seed")),
                division_rank=as_int(standing.get("division_rank")),
                clinched_playoffs=_truthy(standing.get("clinched_playoffs")),
                streak_type=str(streak.get("type")) if streak.get("type") is not None else None,
                streak_length=as_int(streak.get("value")),
            )
        )
    if not result:
        raise ValueError("Standings teams were present but no team rows were parseable")
    return result
