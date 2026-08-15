"""Parse league/{league_key}/settings into a typed LeagueSettings.

This is the piece a typical hosted connector does not expose: the full
stat-modifier table and exact roster-position counts, not just the general
scoring_type string.
"""

from __future__ import annotations

from typing import Any

from ..models import LeagueSettings, RosterPosition, StatModifier
from ._common import as_float, as_int


def parse_league_settings(data: dict[str, Any]) -> LeagueSettings:
    league = data.get("fantasy_content", {}).get("league")
    if not isinstance(league, list) or len(league) < 2:
        raise ValueError("Response is missing the league[meta, settings] pair")

    meta = league[0]
    settings_wrapper = league[1]
    if not isinstance(meta, dict):
        raise ValueError("league[0] (metadata) is not an object")

    settings_list = settings_wrapper.get("settings") if isinstance(settings_wrapper, dict) else None
    if not isinstance(settings_list, list) or not settings_list:
        raise ValueError("league[1].settings is missing or empty")
    settings = settings_list[0]
    if not isinstance(settings, dict):
        raise ValueError("league[1].settings[0] is not an object")

    roster_positions: list[RosterPosition] = []
    for entry in settings.get("roster_positions", []):
        rp = entry.get("roster_position") if isinstance(entry, dict) else None
        if not isinstance(rp, dict):
            continue
        roster_positions.append(
            RosterPosition(
                position=str(rp.get("position", "")).strip(),
                position_type=rp.get("position_type"),
                count=as_int(rp.get("count"), default=0) or 0,
                is_bench=str(rp.get("is_bench", "0")) == "1"
                or str(rp.get("position", "")).upper() in {"BN", "IR"},
            )
        )

    stat_values: dict[str, float] = {}
    modifiers = settings.get("stat_modifiers", {})
    if isinstance(modifiers, dict):
        for entry in modifiers.get("stats", []):
            stat = entry.get("stat") if isinstance(entry, dict) else None
            if not isinstance(stat, dict):
                continue
            stat_id = str(stat.get("stat_id", "")).strip()
            value = as_float(stat.get("value"))
            if stat_id and value is not None:
                stat_values[stat_id] = value

    stat_names: dict[str, str] = {}
    categories = settings.get("stat_categories", {})
    if isinstance(categories, dict):
        for entry in categories.get("stats", []):
            stat = entry.get("stat") if isinstance(entry, dict) else None
            if not isinstance(stat, dict):
                continue
            stat_id = str(stat.get("stat_id", "")).strip()
            name = stat.get("name") or stat.get("display_name") or stat_id
            if stat_id:
                stat_names[stat_id] = str(name)

    stat_modifiers = [
        StatModifier(stat_id=stat_id, name=stat_names.get(stat_id, stat_id), value=value)
        for stat_id, value in stat_values.items()
    ]

    return LeagueSettings(
        league_key=str(meta.get("league_key", "")),
        league_id=str(meta.get("league_id", "")),
        name=str(meta.get("name", "")),
        season=str(meta.get("season", "")),
        num_teams=as_int(meta.get("num_teams"), default=0) or 0,
        scoring_type=str(settings.get("scoring_type", meta.get("scoring_type", ""))),
        uses_faab=str(settings.get("uses_faab", "0")) == "1",
        waiver_rule=str(settings.get("waiver_rule", "")),
        playoff_start_week=as_int(settings.get("playoff_start_week")),
        num_playoff_teams=as_int(settings.get("num_playoff_teams")),
        stat_modifiers=stat_modifiers,
        roster_positions=roster_positions,
    )
