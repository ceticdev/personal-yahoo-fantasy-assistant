# Threat model: why there are no write tools

**Status: no provider write tools exist in this codebase.** Three tests
enforce that, at two different levels:

1. `tests/contract/test_no_write_tools.py` fails if any registered MCP tool
   *name* contains a write verb (add, drop, trade, submit, update, delete...).
2. `tests/contract/test_read_only_transport.py` fails if any Yahoo Fantasy
   data request uses anything but GET -- the write verbs are sabotaged during
   the test, so a PUT hidden inside a read-sounding tool would fail loudly.
3. The same file asserts that the only POST in the package targets Yahoo's
   exact OAuth token endpoint, that no lineup-change resource is named
   anywhere in `src/`, and that the requested scope is exactly `fspt-r` with
   no `fspt-w` code literal in existence.

The name test alone would prove nothing about the wire; that is why the other
two exist.

The standing guardrail this project is built around: never make a provider
change without confirmation. Lineup recommendations are allowed; provider
writes remain manual, performed by the user in Yahoo's own UI.

## Why this is a separate approval, not a follow-on PR

A write tool on a fantasy roster is a small blast radius compared to, say,
a production database, but it is not zero: an add/drop/trade tool that an
assistant calls based on a misread projection or a stale cache can cost a
real roster spot, a waiver claim, or a trade that cannot be undone once the
other side accepts. The read-only version of this server can be wrong and
the cost is a bad recommendation; a write-capable version that is wrong can
be an executed transaction.

## What would have to be true before adding one

1. **Explicit, per-call confirmation.** Not "confirm once per session" --
   the assistant must show the exact transaction (player in, player out,
   FAAB bid if applicable) and get an explicit yes for that specific
   transaction, every time.
2. **A dry-run/preview path that hits the same validation as the real call**,
   so "what would this do" and "do this" cannot silently diverge.
3. **Idempotency and duplicate-submission protection**, since retries after
   a timeout are exactly the scenario that could double-submit a claim.
4. **Freshness gating**: refuse to execute a write if the roster/league state
   backing the decision is older than a short TTL. This server already labels
   every read with `stale`, `age_seconds`, and `refresh_failed`, so the
   signal exists -- but a write tool must *refuse to act* on stale or
   fallback-served data rather than merely warning about it.
5. **Audit logging of every write attempt** (redacted per `SECURITY.md`),
   separate from the general request log, kept longer.
6. **Scope separation at the OAuth level.** The current token is `fspt-r`
   (read-only) end to end. A write tool would need a distinct `fspt-w` token
   requested through a distinct, visibly-labeled consent step -- never a
   silent scope upgrade on the existing token.
7. **A rollback story**, even if it's just "here is exactly what to do by
   hand in the Yahoo UI to undo this," documented per transaction type
   before that transaction type ships.

None of the above exists yet. Until it does, `fspt-w` scope is not requested,
no write tool is registered, and the enforced test stays in the suite.
