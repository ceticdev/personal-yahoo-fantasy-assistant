# Verification notes

Everything reported here is reproducible from this repository alone. No claim
below depends on a file, dataset, or environment that is not in this repo.

## How to reproduce

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

## Last recorded run

- **Date:** August 15, 2026
- **Environment:** Windows 11, CPython 3.11.9, fresh venv, `pip install -e ".[dev]"`
- **Result:** `41 passed, 2 skipped`

The 2 skips are the two POSIX file-mode assertions in
`tests/unit/test_token_vault.py`. They are skipped on Windows because Windows
does not enforce POSIX permission bits — see
[What is NOT verified](#what-is-not-verified). On Linux/macOS they run and are
expected to pass.

## What the suite covers

| Item | Where |
|---|---|
| Parsers round-trip Yahoo-shaped fixtures (settings, roster, free agents, transactions) | `tests/unit/test_parsers.py` |
| `get_league_settings` surfaces the full stat-modifier table, not just `scoring_type` | `tests/unit/test_parsers.py` |
| Starter slots are read from `LeagueSettings.starter_slots()`, not a hardcoded list | `tests/unit/test_optimizer.py` |
| Optimizer's DP result matches an independent Hungarian (`scipy.optimize.linear_sum_assignment`) optimum on a randomized pool | `tests/unit/test_optimizer.py` |
| Ten unique starters; duplicate and flex slots each filled exactly once | `tests/unit/test_optimizer.py` |
| Unfillable roster returns `complete: false` + `missing_slots` + a warning | `tests/unit/test_optimizer.py` |
| Malformed/missing Yahoo sections raise a typed error instead of silently returning empty | `tests/contract/` |
| Token vault round-trips, writes atomically to the target path, rejects malformed files, and never exposes raw tokens via `.redacted()` | `tests/unit/test_token_vault.py` |
| Token vault writes `0600` and repairs loose modes **on POSIX** | `tests/unit/test_token_vault.py` (skipped on Windows) |
| `redact()` masks `access_token` / `refresh_token` / `client_secret` / `authorization` / `password` keys and `Bearer ...` substrings in log **context** payloads | `tests/unit/test_logging_redaction.py` |
| Cache envelope labels every read with `age_seconds`, `ttl_seconds`, and `stale`; an expired key is re-fetched rather than served | `tests/unit/test_cache.py` |
| Projection adapter leaves 40+ fields unavailable unless the caller opts into estimation | `tests/unit/test_projection_adapter.py` |
| Explosive-play model labels every estimate `basis="unfitted_default_placeholder"` unless fit from real history | `tests/unit/test_explosive_play_model.py` |
| No registered MCP tool name contains a write verb (add/drop/trade/submit/update/delete/…) | `tests/contract/test_no_write_tools.py` |

## What is NOT verified

- **No live Yahoo API call has ever been made from this repository.** The
  Yahoo Fantasy Sports API access application is submitted and pending. Yahoo
  access was observed blocked pending provisioning on both integration paths
  that were tried — a hosted connector and this local server — so
  `yahoo/client.py` and `auth/oauth_client.py` are written against Yahoo's
  documented JSON contract and exercised only against synthetic fixtures.
  Nothing here should be read as "live Yahoo integration verified."
- **All fixtures are synthetic.** Every file in `tests/fixtures/` was
  hand-authored to match Yahoo's documented response shape. None was captured
  from Yahoo. League, team, and player identities in them are invented.
- **Stat IDs and stat modifier values in the fixtures are illustrative and
  uncalibrated.** They must be replaced or recalibrated from a sanitized real
  response after Yahoo approval before any specific stat value is trusted.
- **No live FastMCP contract coverage.** The test suite checks parser and model
  contracts and asserts that no write-verb tool is registered. It does not
  start a FastMCP server, drive a stdio client end to end, or verify tool
  schemas over the wire.
- **Windows token files do not get real POSIX `0600` protection.** The vault
  calls `os.chmod(0o600)`, but on Windows that only toggles the read-only
  attribute; group/other bits are not enforced by the filesystem. The `0600`
  guarantee holds on POSIX only. See `docs/SECURITY.md`.
- **Log redaction is not comprehensive.** `redact()` covers structured
  **context** payloads passed via `log_context()`. It does not rewrite the free
  text of a log message itself, and it matches a fixed key list plus a
  `Bearer ...` pattern rather than detecting secrets generally. It is defense
  in depth on top of not logging token material in the first place, not a
  guarantee.
- **There is no stale-fallback behavior.** The cache labels age and staleness
  and re-fetches expired keys; it does not serve an over-age value when a fetch
  fails. Do not read the `stale` flag as evidence of a fallback path.
- **Explosive-play rates are unfitted.** No historical play-by-play dataset was
  available to fit against, so the defaults are placeholders, labeled as such
  in every returned estimate.

## Conclusion

The parts of this build that do not require live Yahoo access — token vault,
parsers, cache, optimizer, projection adapter, explosive-play model, server
wiring, and the no-write-tools guard — are built and tested. The parts that do
require live Yahoo access are structured against the documented API contract
and remain unverified against a real response, pending the Yahoo access
application. That gate has to clear before this server can honestly be called
"connected."
