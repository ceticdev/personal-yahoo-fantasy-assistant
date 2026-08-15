# personal-yahoo-fantasy-assistant (`yahoo-fantasy-mcp-v2`)

A self-hosted, **read-only** Yahoo Fantasy Sports MCP server for one person's
own fantasy football league.

This README is also the reference page for the Yahoo Fantasy Sports API access
application filed against this repository.

## For Yahoo API reviewers

**What this is.** An independent, personal project. It is not affiliated with,
endorsed by, or operated on behalf of Yahoo or any company. It is run locally
by its author, for that author's own Yahoo account, against a **single league**
they play in. There is no hosted service, no multi-tenant deployment, no user
sign-up, and no third party whose data passes through it. **Single user, single
league.**

**Application status.** The Yahoo Fantasy Sports API access application has
been **submitted, and approval is pending**. This server has therefore **not**
been run against live Yahoo data. Everything below describes intended and
implemented behavior verified against synthetic fixtures — see
[Honest status](#honest-status).

**How Yahoo would be used.** Read-only and low-volume. This is a personal
lineup assistant consulted a handful of times a week (roughly around waiver
runs and before kickoff), not a crawler, scraper, or bulk exporter. Responses
are cached in-process with a short TTL so repeated questions in one session do
not produce repeated Yahoo calls. Only the `fspt-r` (read) OAuth scope is
requested; `fspt-w` is never requested.

**Yahoo resources this application intends to read:**

| Resource | Why |
|---|---|
| League settings and stat modifiers | Know the league's actual scoring rules rather than assuming a preset |
| Roster positions | Know the league's real starting slots (including flex) |
| Team rosters | Know which players are on the user's own team |
| Available players (free agents / waivers) | Suggest pickups the user then makes by hand in Yahoo |
| Transactions | Recent league adds/drops/trades for context |
| Standings | Season context for start/sit decisions |
| Matchups | Weekly opponent context for start/sit decisions |

**No write operations exist.** There is no add, drop, trade, waiver claim,
lineup submission, or settings change anywhere in this codebase. That is
enforced by a test (`tests/contract/test_no_write_tools.py`) that fails if any
registered MCP tool name contains a write verb. Every recommendation this
server produces is executed by the user by hand in Yahoo's own UI. The
rationale and the bar that would have to be cleared before any write tool
existed are in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

**Credential handling.** The OAuth client ID/secret come from the environment
at process start. The token pair lives in exactly one file outside the
repository (default `~/.config/yahoo-fantasy-mcp/token.json`), never in the MCP
client config. Tokens are excluded from Git: `.gitignore` blocks `.env`,
`token.json`, `*.token.json`, `.yahoo_token.json`, `*.pem`, and `*.key`, and no
credential or token has ever been committed to this repository. See
[`docs/SECURITY.md`](docs/SECURITY.md), including its explicit note on what
file-permission protection is and is not available on Windows.

## Where this sits in the author's setup

This server is one of three MCP servers, each owning one thing:

| Server | Owns |
|---|---|
| NFL MCP | News, injuries, weather |
| Matty Fantasy MCP | Deterministic custom scoring |
| **This repo** | Yahoo league state and settings, normalization of those responses into typed models, and slot optimization |

Concretely, this repo owns: the OAuth token vault, the Yahoo HTTP client and
cache, typed parsers/models for Yahoo's JSON, and the exact-slot lineup
optimizer that reads its slots from the league's real roster-position table.
It deliberately does **not** compute fantasy points — `projections/adapter.py`
normalizes a stat line into the shape a scoring engine expects and hands it
off. It also does not source news or injury reports.

## Honest status

- **Live Yahoo integration is not verified.** No call in this repository has
  ever been exercised against a live Yahoo response. Yahoo access was observed
  blocked pending provisioning for both the hosted and the local integration
  path that were tried (see [`VERIFICATION-NOTES.md`](VERIFICATION-NOTES.md)).
- **All fixtures under `tests/fixtures/` are synthetic.** They were
  hand-authored to match Yahoo's documented JSON response shape. They were not
  captured from Yahoo, and the league, team, and player identities in them are
  invented. Each fixture says so in its `_fixture_note` field.
- **The stat IDs and stat modifier values in the fixtures are illustrative,
  not calibrated.** They must be replaced or recalibrated from a sanitized real
  response once Yahoo access is granted. The parsers do not depend on any
  particular stat ID being correct — they read whatever the response contains —
  but no specific `stat_value("78")` result from a fixture should be treated as
  authoritative for a real league.
- **The explosive-play rates are unfitted placeholders**, labeled
  `basis="unfitted_default_placeholder"` in every estimate the model returns.

## Layout

```
src/yahoo_fantasy_mcp/
  auth/token_vault.py        single-file OAuth token store, atomic writes
  auth/oauth_client.py       authorization-code + refresh flow, fspt-r scope only
  yahoo/models.py            typed dataclasses: LeagueSettings, StatModifier, RosterPlayer, Transaction
  yahoo/client.py            HTTP wrapper: cache-aware, redacted context logging, typed errors
  yahoo/parsers/             league_settings.py, roster.py, players.py, transactions.py
  cache.py                   TTL cache that labels every read with age and a stale flag
  projections/adapter.py     normalizes raw stat lines from any source into one shape
  projections/explosive_play_model.py   rate model for 40+ plays / long TDs (unfitted)
  optimizer/exact_slot.py    dynamic-program lineup optimizer over the league's real slots
  server.py                  FastMCP stdio entrypoint, read-only tools only
scripts/obtain_yahoo_token.py  one-time interactive OAuth helper
tests/
  fixtures/    synthetic Yahoo-shaped JSON (league settings, roster, free agents, transactions)
  unit/        parser, cache, vault, optimizer, explosive-play model tests
  contract/    parser-vs-model shape checks and the no-write-tools guard
docs/
  ARCHITECTURE.md   design notes and data flow
  THREAT_MODEL.md   why there are no write tools, and what would have to be true first
  SECURITY.md       token handling rules and their platform limits
```

## Setup

Requires Python 3.11+ (`fastmcp` 2.12.3 is the binding constraint; the
`requires-python = ">=3.11"` floor in `pyproject.toml` is deliberate).

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

Then, once Yahoo API access is granted:

```bash
cp .env.example .env             # fill in YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET
python scripts/obtain_yahoo_token.py   # one-time interactive OAuth, read-only scope
```

`.env.example` documents every supported variable and ships with all
credential values blank. Add the stdio entry to your MCP client config,
pointing at `yahoo-fantasy-mcp` (installed via the `pyproject.toml` script
entry) or `python -m yahoo_fantasy_mcp.server`. Do not put tokens or the client
secret in that config file — they belong in `.env` and the token vault file
only.

## Standing guardrails

- No provider writes, in this build or any build that keeps this README's
  promise.
- Every projection/stat response is labeled with its source and whether 40+
  play counts were available or estimated.
- Every cached read is labeled with its age and TTL rather than being served as
  if fresh.
