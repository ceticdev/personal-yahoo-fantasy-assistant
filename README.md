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

**Yahoo resources this application reads.** The table separates what is built
today from what is planned, so nothing here overstates the current state:

| Resource | Status | Why |
|---|---|---|
| League settings and stat modifiers | **Implemented** (`get_league_settings`) | Know the league's actual scoring rules rather than assuming a preset |
| Roster positions | **Implemented** (part of `get_league_settings`) | Know the league's real starting slots, including flex |
| Team rosters | **Implemented** (`get_team_roster`) | Know which players are on the user's own team |
| Available players (free agents / waivers) | **Implemented** (`get_free_agents`) | Suggest pickups the user then makes by hand in Yahoo |
| Transactions | **Implemented** (`get_transactions`) — read only | Recent league adds/drops/trades for context |
| Standings | **Implemented** (`get_league_standings`) | Season context for start/sit decisions |
| Matchups | **Implemented** (`get_weekly_matchups`) | Weekly opponent context for start/sit decisions |

The complete registered tool surface is nine tools: the six Yahoo reads
above, plus `normalize_projection`, `optimize_lineup`, and
`token_vault_status`. The latter three touch no Yahoo endpoint at all.

**No write operations exist.** There is no add, drop, trade, waiver claim,
lineup submission, or settings change anywhere in this codebase. Three
separate tests enforce that: no registered tool name contains a write verb
(`tests/contract/test_no_write_tools.py`), every Yahoo Fantasy data request is
a GET with the write verbs sabotaged, and the only POST in the package goes to
Yahoo's exact OAuth token endpoint
(`tests/contract/test_read_only_transport.py`). The requested scope is exactly
`fspt-r`; `fspt-w` appears in no code literal anywhere. Every recommendation
this server produces is executed by the user by hand in Yahoo's own UI. The
rationale and the bar that would have to be cleared before any write tool
existed are in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

**Credential handling.** The OAuth client ID/secret come from the environment
at process start (optionally via a local `.env`, which is never committed).
The token pair lives in exactly one file outside the repository (default
`~/.config/yahoo-fantasy-mcp/token.json`), never in the MCP client config.

At rest, that file is protected per platform:

* **Windows** (the production machine): the token JSON is encrypted with
  DPAPI, bound to the current Windows user, before it is written. No plaintext
  token is ever stored. This fails closed — if DPAPI is unavailable, the save
  raises rather than falling back to plaintext.
* **POSIX**: the file is written atomically with `0600`, and loose modes are
  repaired on load.

Tokens are excluded from Git: `.gitignore` blocks `.env`, `token.json`,
`*.token.json`, `.yahoo_token.json`, `*.pem`, and `*.key`, and no credential or
token has ever been committed to this repository. Logs are scrubbed of token
material on every path — message, interpolated arguments, structured context,
and rendered exception chains. See [`docs/SECURITY.md`](docs/SECURITY.md) for
the storage format, migration, recovery, and how to revoke the token.

**Failure handling.** Every expected failure — no credentials, no token, a
corrupt or unreadable token, a failed refresh, Yahoo unreachable, Yahoo 401,
Yahoo's provisioning 403 — comes back as a structured result carrying
`error`, `error_type`, `auth_required`, `not_provisioned`, `retryable`, and a
null `data`, rather than an uncaught error. Nothing in that envelope contains a
token, an authorization code, a client secret, an authorization header, or an
uncapped provider body.

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
- **Explosive-play rates have an offline historical calibration**, labeled
  `estimation_basis="provided_slim_pbp_2020_2025_regular_seasons_v1"` on every
  estimate. The six raw slim files are intentionally not shipped, but their
  hashes, row counts, filters, aggregate counts, and derived rates are recorded
  in the package artifact and documented in
  [`docs/EXPLOSIVE_PLAY_CALIBRATION.md`](docs/EXPLOSIVE_PLAY_CALIBRATION.md).
- **Standings and matchup parsing is synthetic-fixture verified, not live
  Yahoo verified.** Those tools remain subject to the same post-approval schema
  acceptance gate as the other Yahoo reads.

What *is* verified, on both Windows and Linux across Python 3.11 and 3.12 in
CI: the full test suite including real FastMCP client/server contract tests
for all nine tools, the read-only transport guarantees, the token protection
and its fail-closed behavior, the stale-fallback policy, log redaction, a
secret scan, and a clean-release archive check.

## Layout

```
src/yahoo_fantasy_mcp/
  env.py                     locates and loads the repository .env (never .env.example)
  config.py                  environment-driven config; real env always beats .env
  errors.py                  typed errors + the structured error envelope
  logging_utils.py           JSON logging with end-to-end secret redaction
  auth/token_vault.py        single-file OAuth token store, atomic writes
  auth/protection.py         Windows DPAPI / POSIX 0600 token protection at rest
  auth/oauth_client.py       authorization-code + refresh flow, fspt-r scope only
  yahoo/models.py            typed settings, roster, standings, matchup, and transaction records
  yahoo/client.py            GET-only HTTP wrapper: cache-aware, typed errors
  yahoo/parsers/             settings, roster, player, transaction, standings, and matchup parsers
  cache.py                   TTL cache with age/stale labeling and stale fallback
  projections/adapter.py     normalizes raw stat lines from any source into one shape
  projections/explosive_play_model.py   calibrated rate model for 40+ plays / long TDs
  projections/explosive_play_calibration.json   versioned offline calibration artifact
  optimizer/exact_slot.py    dynamic-program lineup optimizer over the league's real slots
  server.py                  FastMCP stdio entrypoint, read-only tools only
scripts/
  obtain_yahoo_token.py      one-time interactive OAuth helper
  secret_scan.py             tracked-file secret scan (filenames + categories only)
  make_release.py            git-archive release build + clean-archive verification
  fit_explosive_play_rates.py  reproducible offline fitter/checker (raw inputs not shipped)
tests/
  fixtures/    synthetic Yahoo-shaped JSON (including standings and matchups)
  unit/        env, cache, vault, token protection, redaction, parser, optimizer, model tests
  contract/    FastMCP in-memory client tests, read-only transport, packaging, no-write-tools
docs/
  ARCHITECTURE.md   design notes and data flow
  THREAT_MODEL.md   why there are no write tools, and what would have to be true first
  SECURITY.md       token storage, redaction, migration, recovery, and revocation
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
credential values blank. The server loads a repository `.env` automatically,
including when launched by the installed console script from an unrelated
working directory; real environment variables always take precedence over
`.env`, and `.env.example` itself is never loaded.

To revoke access: delete the token file (its path is reported by
`token_vault_status`) and remove the app's permission in your Yahoo account
settings. See [`docs/SECURITY.md`](docs/SECURITY.md).

Add the stdio entry to your MCP client config,
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
  if fresh. If a refresh fails and previous data is served instead, it is
  flagged `stale: true` with `refresh_failed: true` and a structured
  `refresh_error` — never presented as current.
- A forced refresh never silently falls back to old data, and a parser or
  programming error is never disguised as a stale-data answer.

## Releases

```bash
python scripts/make_release.py     # git archive from HEAD + verification
python scripts/secret_scan.py      # tracked-file secret scan
```

The archive is built with `git archive`, so it contains tracked sources only —
build products and ignored files cannot get in by construction. It is then
verified: a single top-level directory, `.env.example` present, and no `.git`,
`.venv`, `.pytest_cache`, `__pycache__`, `.pyc`, egg-info, `.env`,
token/credential file, key material, local report, or parent-folder document.
The check prints the entry count and SHA-256.
