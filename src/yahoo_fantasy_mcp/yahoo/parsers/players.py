"""Parse league/{league_key}/players (free agents / waivers) into typed rows."""

from __future__ import annotations

from typing import Any

from ..models import FreeAgentPlayer
from ._common import as_float, as_int, flatten_element_list, iter_indexed


def _parse_one(player_array: Any) -> FreeAgentPlayer | None:
    flat = flatten_element_list(player_array)
    if not flat:
        return None
    name_obj = flat.get("name")
    name = name_obj.get("full") if isinstance(name_obj, dict) else None
    if not name:
        return None

    eligible = [
        str(entry["position"])
        for entry in (flat.get("eligible_positions") or [])
        if isinstance(entry, dict) and "position" in entry
    ]

    percent_owned = flat.get("percent_owned")
    owned_value = None
    if isinstance(percent_owned, dict):
        owned_value = as_float(percent_owned.get("value"))
    else:
        owned_value = as_float(percent_owned)

    bye = flat.get("bye_weeks")
    bye_week = as_int(bye.get("week")) if isinstance(bye, dict) else None

    return FreeAgentPlayer(
        player_key=str(flat.get("player_key", "")),
        player_id=str(flat.get("player_id", "")),
        name=str(name),
        editorial_team_abbr=flat.get("editorial_team_abbr"),
        display_position=str(flat.get("display_position", "")),
        eligible_positions=eligible or [str(flat.get("display_position", ""))],
        status=flat.get("status"),
        status_full=flat.get("status_full"),
        percent_owned=owned_value,
        bye_week=bye_week,
    )


def parse_free_agents(data: dict[str, Any]) -> list[FreeAgentPlayer]:
    league = data.get("fantasy_content", {}).get("league")
    if not isinstance(league, list):
        raise ValueError("Response is missing fantasy_content.league")

    players: list[FreeAgentPlayer] = []
    for item in league:
        if not isinstance(item, dict) or "players" not in item:
            continue
        players_container = item["players"]
        if not isinstance(players_container, dict):
            continue
        for entry in iter_indexed(players_container):
            if not isinstance(entry, dict) or "player" not in entry:
                continue
            parsed = _parse_one(entry["player"])
            if parsed is not None:
                players.append(parsed)

    return players
