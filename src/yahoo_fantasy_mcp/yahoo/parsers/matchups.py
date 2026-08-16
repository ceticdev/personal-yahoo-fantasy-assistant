"""Parse Yahoo league scoreboard responses into typed matchup records."""

from __future__ import annotations

from typing import Any

from ..models import LeagueScoreboard, Matchup, MatchupTeam
from ._common import as_float, as_int, flatten_element_list, iter_indexed


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _team(raw_team: Any) -> MatchupTeam | None:
    if not isinstance(raw_team, list) or not raw_team:
        return None
    identity = flatten_element_list(raw_team[0])
    points: dict[str, Any] = {}
    projected: dict[str, Any] = {}
    stats: dict[str, str] = {}
    for part in raw_team[1:]:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("team_points"), dict):
            points = part["team_points"]
        if isinstance(part.get("team_projected_points"), dict):
            projected = part["team_projected_points"]
        team_stats = part.get("team_stats")
        if isinstance(team_stats, dict):
            for item in team_stats.get("stats", []):
                stat = item.get("stat") if isinstance(item, dict) else None
                if isinstance(stat, dict) and stat.get("stat_id") is not None:
                    stats[str(stat["stat_id"])] = str(stat.get("value", ""))
    return MatchupTeam(
        team_key=str(identity.get("team_key", "")),
        team_id=str(identity.get("team_id", "")),
        name=str(identity.get("name", "")),
        points=as_float(points.get("total")),
        projected_points=as_float(projected.get("total")),
        stats=stats,
    )


def parse_weekly_matchups(data: dict[str, Any]) -> LeagueScoreboard:
    """Return the scoreboard week and its matchup/team details."""

    league = data.get("fantasy_content", {}).get("league")
    if not isinstance(league, list):
        raise ValueError("Response is missing fantasy_content.league")
    scoreboard: dict[str, Any] | None = None
    for item in league[1:]:
        if isinstance(item, dict) and isinstance(item.get("scoreboard"), dict):
            scoreboard = item["scoreboard"]
            break
    if scoreboard is None:
        raise ValueError("Response is missing league scoreboard")

    matchups = scoreboard.get("matchups")
    if not isinstance(matchups, dict):
        indexed = scoreboard.get("0")
        if isinstance(indexed, dict):
            matchups = indexed.get("matchups")
    if not isinstance(matchups, dict):
        raise ValueError("Scoreboard is missing matchups")
    week = as_int(scoreboard.get("week"), default=0) or 0
    if as_int(matchups.get("count"), default=None) == 0:
        return LeagueScoreboard(week=week, matchups=[])

    parsed: list[Matchup] = []
    for entry in iter_indexed(matchups):
        raw = entry.get("matchup") if isinstance(entry, dict) else None
        if not isinstance(raw, dict):
            continue
        teams = raw.get("teams")
        if not isinstance(teams, dict):
            wrapper = raw.get("0")
            if isinstance(wrapper, dict):
                teams = wrapper.get("teams")
        team_rows: list[MatchupTeam] = []
        if isinstance(teams, dict):
            for team_entry in iter_indexed(teams):
                team = _team(team_entry.get("team") if isinstance(team_entry, dict) else None)
                if team is not None:
                    team_rows.append(team)
        parsed.append(
            Matchup(
                week=as_int(raw.get("week"), default=week) or week,
                week_start=str(raw["week_start"]) if raw.get("week_start") is not None else None,
                week_end=str(raw["week_end"]) if raw.get("week_end") is not None else None,
                status=str(raw.get("status", "")),
                is_playoffs=_truthy(raw.get("is_playoffs")),
                is_consolation=_truthy(raw.get("is_consolation")),
                is_tied=_truthy(raw.get("is_tied")),
                winner_team_key=(
                    str(raw["winner_team_key"]) if raw.get("winner_team_key") is not None else None
                ),
                teams=team_rows,
            )
        )
    if not parsed:
        raise ValueError("Matchups were present but no matchup rows were parseable")
    return LeagueScoreboard(week=week, matchups=parsed)
