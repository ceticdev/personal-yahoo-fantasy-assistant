"""Automated guardrail: this server must never register a write tool.

Item 8 of the deferred-backlog list says explicitly: "No provider write
tools until a separate, confirmation-gated threat model is approved." This
test makes that a CI-enforced fact instead of a promise in a docstring --
if someone adds `add_player` or `submit_lineup` later, this fails loudly
instead of relying on a human reviewer to notice.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yahoo_fantasy_mcp import server

WRITE_VERBS = (
    "add",
    "drop",
    "trade",
    "submit",
    "set_lineup",
    "update",
    "delete",
    "remove",
    "create",
    "claim",
    "waiver_claim",
    "change_setting",
)


def test_no_registered_tool_name_implies_a_write():
    tool_names = list(server.mcp._tool_manager._tools.keys())
    assert tool_names, "expected at least one registered tool"
    for name in tool_names:
        lowered = name.lower()
        for verb in WRITE_VERBS:
            assert verb not in lowered, (
                f"tool '{name}' looks like a write tool ('{verb}') -- this server is "
                "read-only until docs/THREAT_MODEL.md is updated and approved"
            )


def test_expected_read_only_tools_are_present():
    tool_names = set(server.mcp._tool_manager._tools.keys())
    expected = {
        "get_league_settings",
        "get_team_roster",
        "get_free_agents",
        "get_transactions",
        "normalize_projection",
        "optimize_lineup",
        "token_vault_status",
    }
    assert expected <= tool_names
