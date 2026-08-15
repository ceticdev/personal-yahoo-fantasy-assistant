"""Parse team/{team_key}/roster into typed RosterPlayer rows."""

from __future__ import annotations

from typing import Any

from ..models import RosterPlayer
from ._common import as_int, flatten_element_list, iter_indexed


def _extract_selected_position(container: dict[str, Any]) -> str | None:
    selected = container.get("selected_position")
    if isinstance(selected, dict):
        if "position" in selected:
            return selected.get("position")
        for key, value in selected.items():
            if key == "count":
                continue
            if isinstance(value, dict) and "position" in value:
                return value["position"]
    elif isinstance(selected, list):
        flat = flatten_element_list(selected)
        return flat.get("position")
    return None


def _extract_eligible_positions(container: dict[str, Any]) -> list[str]:
    raw = container.get("eligible_positions")
    positions: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and "position" in entry:
                positions.append(str(entry["position"]))
    return positions


def _extract_bye(container: dict[str, Any]) -> int | None:
    bye = container.get("bye_weeks")
    if isinstance(bye, dict):
        return as_int(bye.get("week"))
    return None


def _parse_one_player(player_array: Any) -> RosterPlayer | None:
    flat = flatten_element_list(player_array)
    if not flat:
        return None
    name_obj = flat.get("name")
    name = name_obj.get("full") if isinstance(name_obj, dict) else None
    if not name:
        return None

    return RosterPlayer(
        player_key=str(flat.get("player_key", "")),
        player_id=str(flat.get("player_id", "")),
        name=str(name),
        editorial_team_abbr=flat.get("editorial_team_abbr"),
        display_position=str(flat.get("display_position", "")),
        eligible_positions=_extract_eligible_positions(flat) or [str(flat.get("display_position", ""))],
        selected_position=_extract_selected_position(flat),
        status=flat.get("status"),
        status_full=flat.get("status_full"),
        bye_week=_extract_bye(flat),
    )


def parse_team_roster(data: dict[str, Any]) -> list[RosterPlayer]:
    team = data.get("fantasy_content", {}).get("team")
    if not isinstance(team, list):
        raise ValueError("Response is missing fantasy_content.team")

    players: list[RosterPlayer] = []
    for item in team:
        if not isinstance(item, dict) or "roster" not in item:
            continue
        roster_data = item["roster"]
        players_container = None
        if isinstance(roster_data, dict):
            zero = roster_data.get("0")
            if isinstance(zero, dict):
                players_container = zero.get("players")
            if players_container is None:
                players_container = roster_data.get("players")
        if not isinstance(players_container, dict):
            continue

        for entry in iter_indexed(players_container):
            if not isinstance(entry, dict) or "player" not in entry:
                continue
            parsed = _parse_one_player(entry["player"])
            if parsed is not None:
                players.append(parsed)

    return players
