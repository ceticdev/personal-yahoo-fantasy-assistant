# Verification notes

The code/test/package claims below are reproducible from this repository alone.
The tracked explosive-play artifact also records the hashes, row counts,
filters, totals, and rates produced from the supplied slim PBP inputs; those
raw inputs are deliberately excluded from the repository and release.

## How to reproduce

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest -rs
python scripts/secret_scan.py
python scripts/make_release.py
```

## Last recorded run

- **Date:** August 15, 2026
- **Environment:** Linux, CPython 3.12, fresh venv, `pip install -e ".[dev]"`
- **Result:** `217 passed, 1 skipped` in the clean handoff build

The one skip is the real Windows DPAPI round trip, which is Windows-only. On
Linux, POSIX mode assertions run and the DPAPI path is covered by mocks. In
the Windows matrix job, the real DPAPI round trip runs while POSIX-only mode
assertions skip. Every platform-specific guarantee is asserted in CI.

CI runs the same suite on **Ubuntu and Windows** across **Python 3.11 and
3.12** (`.github/workflows/ci.yml`), with no Yahoo credentials and no
repository secrets.

## What the suite covers

| Area | Item | Where |
|---|---|---|
| Config | Repository `.env` is loaded; real environment variables override it; lookup works from an unrelated working directory; a missing `.env` is a silent no-op; `.env.example` is never loaded | `tests/unit/test_env_loading.py` |
| Parsing | Parsers round-trip Yahoo-shaped fixtures (settings, roster, free agents, transactions, standings, weekly matchups) | `tests/unit/test_parsers.py` |
| Parsing | `get_league_settings` surfaces the full stat-modifier table, not just `scoring_type` | `tests/unit/test_parsers.py` |
| Parsing | Malformed/missing Yahoo sections raise a typed error instead of silently returning empty | `tests/contract/` |
| Optimizer | Starter slots come from `LeagueSettings.starter_slots()`, not a hardcoded list | `tests/unit/test_optimizer.py` |
| Optimizer | DP result matches an independent Hungarian (`scipy.optimize.linear_sum_assignment`) optimum on a randomized pool | `tests/unit/test_optimizer.py` |
| Optimizer | Ten unique starters; duplicate and flex slots each filled exactly once; unfillable rosters report `complete: false` + `missing_slots` | `tests/unit/test_optimizer.py` |
| Token storage | DPAPI-protected file contains no plaintext token material and round-trips | `tests/unit/test_token_protection.py` |
| Token storage | A DPAPI failure **fails closed** — raises, writes nothing, leaves no temp file, never falls back to plaintext | `tests/unit/test_token_protection.py` |
| Token storage | A legacy plaintext token is migrated to encrypted form on first load | `tests/unit/test_token_protection.py` |
| Token storage | A token encrypted for another Windows user reports a typed, actionable error | `tests/unit/test_token_protection.py` |
| Token storage | Real DPAPI round trip against `crypt32` | `tests/unit/test_token_protection.py` (Windows only) |
| Token storage | POSIX `0600` write and loose-mode repair | `tests/unit/test_token_vault.py` (POSIX only) |
| Token storage | Status output and `.redacted()` never expose raw token values | both files above |
| Redaction | A sentinel secret never appears in captured output via message, interpolated args, structured context, exception text, or a chained exception | `tests/unit/test_logging_redaction.py` |
| Redaction | Repeated `configure_logging()` does not stack handlers; records do not propagate to non-redacting root handlers | `tests/unit/test_logging_redaction.py` |
| Caching | Fresh hit → `stale=false`; expired + success → new data, `stale=false`; expired + transport/service failure → previous data with `stale=true`, real `age_seconds`, `refresh_failed=true`, structured `refresh_error`; no cache + failure → error; `force_refresh` + failure → error, never a silent fallback; parser/validation/programming errors never disguised as stale data | `tests/unit/test_cache.py` (injected clock, no sleeping) |
| MCP contract | All nine tools discoverable through a real in-memory FastMCP `Client`, with successful pure-tool calls and mocked Yahoo reads plus the full structured-failure matrix | `tests/contract/test_fastmcp_contract.py` |
| MCP contract | No expected operational failure surfaces as an uncaught FastMCP `ToolError` | `tests/contract/test_fastmcp_contract.py` |
| Read-only | Every Yahoo Fantasy data request uses GET, with `httpx.put/post/patch/delete` sabotaged during the test | `tests/contract/test_read_only_transport.py` |
| Read-only | The only POST in the package targets Yahoo's exact token endpoint; no write-verb call exists elsewhere in `src/` | `tests/contract/test_read_only_transport.py` |
| Read-only | The requested OAuth scope is exactly `fspt-r`; no `fspt-w` code literal exists | `tests/contract/test_read_only_transport.py` |
| Read-only | No registered MCP tool name contains a write verb | `tests/contract/test_no_write_tools.py` |
| Projections | `estimation_basis` is null when nothing was estimated, names the packaged 2020-2025 PBP calibration for the default model, and names caller-fitted models; provided / estimated / unavailable / zero-valued fields stay distinguishable | `tests/unit/test_projection_adapter.py`, `tests/unit/test_pbp_calibration.py` |
| Packaging | The release checker rejects each forbidden category (`.git`, `.venv`, `.pytest_cache`, `__pycache__`, `.pyc`, egg-info, `.env`, token/credential files, key material, local reports, parent-folder documents), requires one top-level directory, and requires `.env.example` | `tests/contract/test_release_packaging.py` |
| Packaging | The secret scanner finds a planted secret and reports categories without values | `tests/contract/test_release_packaging.py` |

## What is NOT verified

- **No live Yahoo API call has ever been made from this repository.** The
  Yahoo Fantasy Sports API access application is submitted and pending. Yahoo
  access was observed blocked pending provisioning on both integration paths
  that were tried — a hosted connector and this local server — so
  `yahoo/client.py` and `auth/oauth_client.py` are written against Yahoo's
  documented JSON contract and exercised only against synthetic fixtures and
  mocks. Nothing here should be read as "live Yahoo integration verified."
- **All fixtures are synthetic.** Every file in `tests/fixtures/` was
  hand-authored to match Yahoo's documented response shape. None was captured
  from Yahoo. League, team, and player identities in them are invented.
- **Stat IDs and stat modifier values in the fixtures are illustrative and
  uncalibrated.** They must be replaced or recalibrated from a sanitized real
  response after Yahoo approval before any specific stat value is trusted.
- **Standings and matchups are not live-verified.** The tools and parsers exist,
  but their fixtures are synthetic and need post-approval schema acceptance.
- **Explosive-play calibration is offline.** It was fitted from the supplied
  2020-2025 slim regular-season PBP files, not Yahoo data. Raw inputs are not
  shipped; the artifact records their hashes and derived audit evidence.
- **The mocked Yahoo responses are shaped by us, not by Yahoo.** The contract
  tests prove this server behaves correctly *given* Yahoo's documented shape.
  They cannot prove the documented shape matches production. Re-run
  `tests/contract/` against a sanitized live pull once access is granted.
- **DPAPI is not a defense against the same user account.** It binds the token
  to the current Windows user, which stops another user, another machine, or a
  copied backup file from reading it. Malware already running as that user can
  still ask DPAPI to decrypt. That is inherent to the mechanism.

## Conclusion

The parts of this build that do not require live Yahoo access — configuration,
token storage and protection, redaction, caching and stale fallback, parsers,
optimizer, projection provenance, the MCP tool contract, the read-only
guarantees, and packaging — are built and tested on both platforms. The parts
that require live Yahoo access remain unverified against a real response,
pending the access application. That gate has to clear before this server can
honestly be called "connected."
