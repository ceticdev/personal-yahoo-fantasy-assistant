# yahoo-fantasy-mcp-v2

Self-hosted, **read-only** Yahoo Fantasy Sports MCP. Built as the deferred
engineering backlog item from `MCP-PLAN-AND-CLAUDE-HANDOFF.md`: a focused v2
rather than extending `fantasy-football-mcp-public` in place.

## What this is

A local MCP server that owns three things the earlier candidates did not
combine correctly:

1. **A real OAuth token vault.** Tokens live in one file outside the repo,
   written with `0600` permissions, never in client config, never logged
   unredacted.
2. **Typed Yahoo parsers with fixture tests**, including a `get_league_settings`
   tool that returns Yahoo's *full* stat modifier and roster-position tables
   (not just the general scoring type Flaim exposes).
3. **A projection adapter and exact-slot optimizer** that take raw stat
   distributions plus a historical explosive-play model, so 40+ yard plays
   and long touchdowns are estimated rather than silently dropped the way
   ordinary season-total projections drop them.

Every read carries a source timestamp, a cache age, and a `stale` flag. There
are **no write tools** — no add/drop/trade/lineup-submit. That is intentional;
see `docs/THREAT_MODEL.md`.

## Status

**Not yet connected to live Yahoo data.** Per `VERIFICATION-NOTES.md`
(Aug 15, 2026), Yahoo's Fantasy Sports API is behind a manual provisioning
queue for third-party apps, and this project has not been through it. The
parsers, cache, token vault, optimizer, and projection layer are built and
tested against fixtures that mirror Yahoo's documented JSON response shape.
Swap in a real `YahooOAuthClient` session once API access is granted; the
parser and tool contracts do not change.

## Layout

```
src/yahoo_fantasy_mcp/
  auth/token_vault.py        file-based OAuth token store, 0600, atomic writes
  auth/oauth_client.py       authorization-code + refresh flow, fspt-r scope only
  yahoo/models.py            typed dataclasses: LeagueSettings, StatModifier, RosterPlayer, Transaction
  yahoo/client.py            HTTP wrapper: cache-aware, redacted logging, raises typed errors
  yahoo/parsers/             league_settings.py, roster.py, players.py, transactions.py
  cache.py                   TTL cache that surfaces staleness instead of hiding it
  projections/adapter.py     normalizes raw stat lines from any source into one shape
  projections/explosive_play_model.py   historical rate model for 40+ plays / long TDs
  optimizer/exact_slot.py    dynamic-program lineup optimizer over the league's real slots
  server.py                  FastMCP stdio entrypoint, read-only tools only
scripts/obtain_yahoo_token.py  one-time interactive OAuth helper, prints nothing secret
tests/
  fixtures/    Yahoo-shaped JSON fixtures (league settings, roster, free agents, transactions)
  unit/        parser, cache, vault, optimizer, explosive-play model tests
  contract/    fixture-vs-model contract checks (fails loudly if Yahoo's shape assumption breaks)
docs/
  ARCHITECTURE.md   design notes and how this differs from the two earlier candidates
  THREAT_MODEL.md    why there are no write tools yet, and what has to be true before there are
  SECURITY.md        token handling rules
```

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest -q
```

Then, once Yahoo API access is granted:

```bash
cp .env.example .env             # fill in YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET
python scripts/obtain_yahoo_token.py   # one-time interactive OAuth, read-only scope
```

Add the stdio entry to your MCP client config, pointing at
`yahoo-fantasy-mcp` (installed via the `pyproject.toml` script entry) or
`python -m yahoo_fantasy_mcp.server`. Do not put tokens or the client secret
in that config file — they belong in `.env` and the token vault file only.

## Guardrails carried over from the plan

- No provider writes. Ever, in this build.
- Every projection/stat response is labeled with its source and whether
  40+ play counts were available or estimated.
- Stale data is flagged, not silently served.

## Environment note (mirrors matty-fantasy-mcp's finding)

`pyproject.toml` correctly declares `requires-python = ">=3.11"` (fastmcp
2.12.3 is the binding constraint). The build/test sandbox used to write this
repo only had Python 3.10.12, the same situation `VERIFICATION-RUN-NOTES.md`
hit with matty-fantasy-mcp. `pip install -e .` will refuse to install on
3.10 for that reason -- that's correct behavior, not a bug. Tests were run
via `PYTHONPATH=src pytest -q` in that sandbox instead (41/41 passing); use a
real 3.11+ interpreter for the editable install and the `yahoo-fantasy-mcp`
script entry point in production.
