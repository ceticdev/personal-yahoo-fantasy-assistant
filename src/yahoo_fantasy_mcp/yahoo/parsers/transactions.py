"""Parse league/{league_key}/transactions into typed Transaction rows."""

from __future__ import annotations

from typing import Any

from ..models import Transaction, TransactionPlayerMove
from ._common import as_int, flatten_element_list, iter_indexed


def _parse_player_move(player_entry: Any) -> TransactionPlayerMove | None:
    if not isinstance(player_entry, dict) or "player" not in player_entry:
        return None
    parts = player_entry["player"]
    if not isinstance(parts, list) or len(parts) < 2:
        return None
    identity = flatten_element_list(parts[0])
    move_wrapper = parts[1]
    move_list = move_wrapper.get("transaction_data") if isinstance(move_wrapper, dict) else None
    move = flatten_element_list(move_list) if move_list is not None else {}

    name_obj = identity.get("name")
    name = name_obj.get("full") if isinstance(name_obj, dict) else None
    if not name:
        return None

    return TransactionPlayerMove(
        player_key=str(identity.get("player_key", "")),
        name=str(name),
        source_type=str(move.get("source_type", "")),
        destination_type=str(move.get("destination_type", "")),
        source_team_key=move.get("source_team_key"),
        destination_team_key=move.get("destination_team_key"),
    )


def parse_transactions(data: dict[str, Any]) -> list[Transaction]:
    league = data.get("fantasy_content", {}).get("league")
    if not isinstance(league, list):
        raise ValueError("Response is missing fantasy_content.league")

    transactions: list[Transaction] = []
    for item in league:
        if not isinstance(item, dict) or "transactions" not in item:
            continue
        container = item["transactions"]
        if not isinstance(container, dict):
            continue
        for entry in iter_indexed(container):
            if not isinstance(entry, dict) or "transaction" not in entry:
                continue
            tx_parts = entry["transaction"]
            if not isinstance(tx_parts, list) or len(tx_parts) < 1:
                continue
            meta = tx_parts[0] if isinstance(tx_parts[0], dict) else {}
            players: list[TransactionPlayerMove] = []
            if len(tx_parts) > 1 and isinstance(tx_parts[1], dict):
                players_container = tx_parts[1].get("players", {})
                if isinstance(players_container, dict):
                    for player_entry in iter_indexed(players_container):
                        move = _parse_player_move(player_entry)
                        if move is not None:
                            players.append(move)

            transactions.append(
                Transaction(
                    transaction_key=str(meta.get("transaction_key", "")),
                    transaction_type=str(meta.get("type", "")),
                    status=str(meta.get("status", "")),
                    timestamp=as_int(meta.get("timestamp"), default=0) or 0,
                    players=players,
                )
            )

    return transactions
