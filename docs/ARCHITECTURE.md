# Architecture

## Where this fits

The author's working setup is three MCP servers, each owning one thing:

| Server | Owns |
|---|---|
| NFL MCP | News, injuries, weather |
| Matty Fantasy MCP | Deterministic custom scoring |
| **This repo** | Yahoo league state and settings, normalization into typed models, and slot optimization |

This repo's share of that split is: the OAuth token vault, the Yahoo HTTP
client and its cache, typed parsers and models for Yahoo's JSON (notably the
*full* stat-modifier and roster-position tables, not just the general scoring
type), and an exact-slot optimizer whose slots come from the league's real
roster-position table rather than a hardcoded list.

### On alternatives

A hosted Yahoo connector (Flaim) was evaluated before this repo was written.
It is not the case that it, or any other integration path, bypasses Yahoo's
API approval process — **Yahoo access was observed blocked pending
provisioning on both the hosted connector and this local server.** Any earlier
note in this project suggesting a hosted option avoids Yahoo's approval queue
was wrong and has been removed. This repo needs its own Yahoo application and
its own approval, which is submitted and pending; see `VERIFICATION-NOTES.md`.

The reason this repo exists is therefore not approval avoidance. It is
ownership: a locally-controlled token vault, the complete stat-modifier table,
and a testable optimizer/projection layer.

## Data flow

```
Yahoo Fantasy Sports API   (read-only, fspt-r; access pending approval)
        |
        v
  auth/oauth_client.py  <---> auth/token_vault.py (single file, outside the repo)
        |
        v
  yahoo/client.py  ---cache---> cache.py (TTL; labels age + stale on every read)
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

- **No scoring engine in this repo.** `projections/adapter.py` normalizes stat
  lines into the shape a scoring engine expects; it does not compute points.
  Deterministic custom scoring stays in Matty Fantasy MCP.
- **No news or injury sourcing.** That belongs to NFL MCP.
- **No write tools.** See `THREAT_MODEL.md`.
- **No live Yahoo integration test.** Yahoo API access is pending approval, so
  the parsers are exercised only against synthetic fixtures shaped to match
  Yahoo's documented JSON contract. Once access is granted, re-run
  `tests/contract/` against a sanitized live pull to confirm the shape
  assumption still holds.

## Known open item: fixtures and stat IDs are synthetic

Every file in `tests/fixtures/` is hand-authored and synthetic — not captured
from Yahoo. The league, team, and player identities in them are invented, and
the stat IDs and modifier values are illustrative rather than verified against
a live `game/{game_key}/stat_categories` response.

The parser contract (`league_settings.py`) does not depend on any specific stat
ID being correct — it reads whatever `stat_modifiers.stats` contains — but the
fixtures themselves must be replaced or recalibrated from a sanitized real
response once Yahoo access is granted. Until then, no `stat_value(...)` result
derived from a fixture is authoritative for a real league's scoring rules.

## Known open item: explosive-play rates are unfitted

`projections/explosive_play_model.py` ships with placeholder default rates,
labeled `basis="unfitted_default_placeholder"` in every estimate it returns.
Call `fit_from_history()` with real season data before trusting an *estimated*
40+ play count in a real decision. Until then, prefer leaving 40+ fields
unavailable (the default behavior) over a guessed estimate.
