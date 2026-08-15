# Architecture

## Where this fits

Per `deliverable/MCP-PLAN-AND-CLAUDE-HANDOFF.md`, the working stack is three
servers, each owning one thing:

| Server | Owns |
|---|---|
| Flaim | Live Yahoo state (roster, standings, matchups, transactions) via OAuth without a personal Yahoo developer approval |
| NFL MCP | Current news, injuries, weather |
| Matty Fantasy MCP | Deterministic custom scoring + exact-slot optimization for league 371856 |
| **This repo (v2)** | The piece none of the above cover: a real token vault, the *full* Yahoo stat-modifier/roster-position table, an explosive-play estimator, and a portable copy of the exact-slot optimizer that reads slots from live settings instead of a hardcoded list |

This is not a replacement for Flaim. Flaim already solves OAuth-without-a-
personal-developer-approval, which this repo does not attempt to solve (it
still needs its own Yahoo app + manual API provisioning, per
`VERIFICATION-RUN-NOTES.md` section 4). This repo exists for the two gaps
the plan flagged Flaim does not close: the full stat-modifier table, and a
locally-owned, testable optimizer/projection layer.

## Data flow

```
Yahoo Fantasy Sports API
        |
        v
  auth/oauth_client.py  (fspt-r only) <---> auth/token_vault.py (0600 file)
        |
        v
  yahoo/client.py  ---cache---> cache.py (TTL + stale flag)
        |
        v
  yahoo/parsers/*.py  -> yahoo/models.py (typed dataclasses)
        |
        v
  server.py tools (get_league_settings, get_team_roster, get_free_agents,
                    get_transactions)
        |
        v
  projections/adapter.py + explosive_play_model.py
        |                        (normalizes raw stats; does NOT score)
        v
  [hand off stat_line to a separate scoring MCP, e.g. matty-fantasy-mcp]
        |
        v
  optimizer/exact_slot.py  (slots come from LeagueSettings.starter_slots())
```

## Deliberate non-goals

- **No scoring engine in this repo.** `projections/adapter.py` normalizes
  stat lines into the shape a scoring engine expects; it does not compute
  points. That stays in Matty Fantasy MCP, which is already built, tested,
  and verified against explicit acceptance gates
  (`VERIFICATION-RUN-NOTES.md` section 1).
- **No write tools.** See `THREAT_MODEL.md`.
- **No live Yahoo integration test in this build.** Yahoo's Fantasy Sports
  API was behind a manual provisioning queue (403 for both reviewed
  connectors) as of the Aug 15 2026 verification run. Parsers are built and
  tested against fixtures shaped to match Yahoo's documented JSON contract;
  swap in real API access once granted and re-run
  `tests/contract/` against a live pull to confirm the shape assumption
  still holds.

## Known open item: stat ID calibration

`tests/fixtures/league_settings_371856.json` uses illustrative stat IDs and
values, not a verified pull from Yahoo's `game/{game_key}/stat_categories`
resource. The parser contract (`league_settings.py`) does not depend on any
specific stat ID being correct -- it reads whatever `stat_modifiers.stats`
contains -- but the *fixture itself* should be regenerated from a real Yahoo
response before anyone treats a specific `stat_value("78")` call as
authoritative for league 371856's actual 40+ yard play modifier. Until then,
the authoritative source for that number remains
`deliverable/matty-fantasy-mcp/fantasy_league_mcp/profile.py`, which was
hand-verified against the league commissioner's stated rules.

## Known open item: explosive-play rates are unfitted

`projections/explosive_play_model.py` ships with placeholder default rates,
clearly labeled `basis="unfitted_default_placeholder"`. Call
`fit_from_history()` with real season data before trusting an *estimated*
40+ play count in a real decision. Until then, prefer leaving 40+ fields
unavailable (the default behavior) over a guessed estimate.
