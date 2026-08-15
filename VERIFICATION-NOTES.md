# Verification Notes -- yahoo-fantasy-mcp-v2 build

**Run:** August 15, 2026, same session as `deliverable/VERIFICATION-RUN-NOTES.md`.
**Scope:** the deferred-engineering-backlog item from `MCP-PLAN-AND-CLAUDE-HANDOFF.md`
("If a single self-hosted Yahoo MCP is still desired later, build it as a
focused v2 rather than extending the legacy optimizer in place").

## What was verified

| Item | Result |
|---|---|
| `pytest -q` (via `PYTHONPATH=src`, Python 3.10.12 -- see README env note) | **41 passed, 0 failed** |
| Parsers round-trip Yahoo-shaped fixtures (settings, roster, free agents, transactions) | PASS |
| `get_league_settings` returns the full stat-modifier table, not just `scoring_type` | PASS (`stat_value("78")==3.0`, `stat_value("79")==2.0`, etc.) |
| Optimizer's starter slots come from live `LeagueSettings.starter_slots()`, not a hardcoded list | PASS |
| Optimizer DP result matches an independent Hungarian (scipy `linear_sum_assignment`) optimum on a random 18-player pool | PASS |
| Ten unique starters, duplicate/flex slots each filled once | PASS |
| Unfillable roster returns `complete: false` + `missing_slots` + warning | PASS |
| Token vault writes `0600`, atomic replace, round-trips, repairs loose permissions, never exposes raw tokens via `.redacted()` | PASS |
| Structured logging redacts `access_token`/`refresh_token`/`client_secret`/`Bearer ...` | PASS |
| Cache surfaces `age_seconds` / `stale` instead of hiding it | PASS |
| Projection adapter leaves 40+ fields **unavailable** (not silently zeroed-and-forgotten) unless the caller explicitly opts into estimation | PASS |
| Explosive-play model labels every estimate `basis="unfitted_default_placeholder"` unless fit from real history | PASS |
| No registered MCP tool name contains a write verb (add/drop/trade/submit/update/delete/...) | PASS, enforced by `tests/contract/test_no_write_tools.py` |
| `server.py` tools run end-to-end without Yahoo credentials configured and return a labeled error instead of crashing | PASS (manual check, `token_vault_status` / `get_league_settings` both returned clean structured results) |

## What was NOT verified (and why)

- **No live Yahoo API call was made.** Per `deliverable/VERIFICATION-RUN-NOTES.md`
  section 4, Yahoo's Fantasy Sports API returned 403 / `additional_authorization_required`
  for both reviewed connectors that day -- a manual provisioning-queue gate,
  not an account or OAuth bug. This repo was never going to clear that gate
  in the same session, so `yahoo/client.py` and `auth/oauth_client.py` are
  built and unit-tested against Yahoo's documented JSON contract shape, not
  exercised against a live response. Treat the fixture-shaped JSON in
  `tests/fixtures/` as illustrative, not verified-correct in every field
  (see `docs/ARCHITECTURE.md`, "Known open item: stat ID calibration").
- **Explosive-play rates are unfitted placeholders**, clearly labeled as
  such at the code and doc level. No historical play-by-play dataset was
  available in this session to fit against (the plan's own CBS projections
  source was returning HTTP 404 for the target week per the parent
  verification run).
- **No editable pip install** in the build sandbox (Python 3.10.12 vs the
  declared `>=3.11` floor) -- tests ran via `PYTHONPATH=src` instead. Re-run
  `pip install -e ".[dev]" && pytest -q` on a real 3.11+ box before treating
  this as done.

## Conclusion

The parts of this build that don't require live Yahoo access -- token vault,
parsers, cache, optimizer, projection adapter, explosive-play model, server
wiring, and the no-write-tools guardrail -- are built and tested, 41/41
green. The parts that do require live Yahoo access are correctly structured
against the documented API contract but unverified against a real response,
for the same external reason (the provisioning queue) that blocked both
candidates reviewed earlier that day. That gate has to clear before this
server can be called "connected," not before it can be called "built."
