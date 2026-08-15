# Security notes

## Token storage

The OAuth token pair lives in exactly one file: the path at
`YAHOO_FANTASY_MCP_TOKEN_PATH` (default
`~/.config/yahoo-fantasy-mcp/token.json`), outside the repository. It is
always written by an atomic replace, so a crash mid-write cannot leave a
half-written token file.

How it is protected at rest depends on the platform, because the two platforms
offer genuinely different guarantees.

### Windows: DPAPI encryption (the production platform)

Windows does not enforce POSIX permission bits — `os.chmod` there only toggles
the read-only attribute — so file modes alone would leave the token pair
sitting in plaintext. Instead, the token JSON is encrypted with the Windows
Data Protection API (`CryptProtectData`), bound to the **current Windows
user**, before anything is written to disk.

On-disk format:

```json
{
  "format": "dpapi-v1",
  "platform": "win32",
  "ciphertext": "<base64 of the DPAPI blob>"
}
```

**Why DPAPI** over the alternatives considered:

* vs. **Windows Credential Manager**: DPAPI needs no third-party dependency
  (it is a `ctypes` call into `crypt32.dll`), has no ~2.5 KB credential-blob
  size limit, and preserves the "one file, atomically replaced" model the rest
  of the package is built around.
* vs. **a restricted ACL**: an ACL still leaves the token in plaintext on
  disk. Encryption is a stronger property than an access-control entry that a
  backup, a sync client, or an administrator can step around.

**Fail closed.** If DPAPI is unavailable or a protect call fails, the save
raises `TokenProtectionError` and writes nothing. There is no fallback to a
plaintext token on Windows — not as a convenience, not as a degraded mode.
`tests/unit/test_token_protection.py` asserts this, including that no partial
or temp file is left behind.

### POSIX: `0600` plus atomic replace

Unchanged from before. The file is the token JSON, written atomically with
`0600`, and `load()` repairs group/other-readable modes rather than trusting
them.

### Migration

A Windows install that still has a pre-hardening plaintext token file will
read it once, immediately rewrite it in DPAPI form, and continue. After the
first load, the plaintext no longer exists on disk. No operator action is
required.

### Recovery

A DPAPI blob is bound to the Windows user account (and machine) that created
it. So:

* copying the token file to another machine, or opening it as a different
  Windows user, **will not work** — by design;
* the failure is reported as a typed, actionable error rather than a crash;
* recovery is to re-run `python scripts/obtain_yahoo_token.py` on the target
  machine, as that account.

The same applies to backups: a restored token file is only usable by the same
user on the same machine.

### Revoking / clearing the token

1. Delete the token file. `token_vault_status` reports its exact path;
   `TokenVault.clear()` is the programmatic equivalent.
2. Remove the application's access in Yahoo's account settings
   (Account Info → Apps connected to your account). Deleting the local file
   stops *this* machine from using the token; revoking at Yahoo invalidates
   it everywhere.

Do both if you believe the token was exposed.

## What the vault does not store

The vault stores `access_token`, `refresh_token`, `expires_at`, `scope`, and
`obtained_at`. It does **not** store `client_id`/`client_secret` — those come
from the environment (or a local, uncommitted `.env`) at process start, so a
leaked token file alone cannot mint new tokens for the app.

The MCP client config (e.g. Claude Desktop's `claude_desktop_config.json`)
never contains a token or a client secret. It only points at this process and,
optionally, the `YAHOO_FANTASY_MCP_TOKEN_PATH`/`.env` location.

Only `fspt-r` (read-only) scope is ever requested. `fspt-w` appears in no code
literal anywhere in `src/`, which is enforced by
`tests/contract/test_read_only_transport.py`.

## Logging

Redaction covers every path by which text reaches a log record:

1. the formatted message (`record.getMessage()`, i.e. after `%`-interpolation);
2. the positional logger arguments, post-interpolation;
3. the structured `context` payload from `log_context()`;
4. rendered exception text, including chained `__cause__`/`__context__`
   exceptions;
5. bearer-token-shaped and secret-assignment-shaped substrings anywhere in the
   above.

Two mechanisms do the work:

* **Registered secrets.** `register_secret()` records exact values known to be
  secret — the client secret at config load, and the access/refresh tokens
  whenever a token is saved or loaded — so they are struck literally wherever
  they appear, regardless of how they got there. This is the strong guarantee,
  and `tests/unit/test_logging_redaction.py` proves a sentinel secret never
  appears in captured output through any of the five channels above.
* **Pattern matching.** Secret-shaped keys, `Bearer ...`, `key=value`
  assignments with secret-shaped keys, Yahoo consumer-key and JWT shapes. This
  catches values that were never registered.

Handler hygiene: `configure_logging()` is idempotent — repeated calls re-apply
the level but never stack a second handler — and `propagate` is set to `False`
so records never reach root handlers that do not redact.

This is still defense in depth, not a substitute for not logging token
material in the first place: `yahoo/client.py` never logs a response body on
the success path, and provider error bodies are scrubbed and capped at 200
characters before they reach any message or envelope.

## Error output

MCP tools return structured envelopes (`error`, `error_type`, `auth_required`,
`not_provisioned`, `retryable`, `data`) rather than raising. Those envelopes
never contain raw tokens, authorization codes, client secrets, authorization
headers, or uncapped provider bodies. Unexpected exceptions are reduced to a
scrubbed `internal_error` rather than surfacing a traceback to the client.

## Keeping credentials out of Git

`.gitignore` blocks `.env`, `.env.*` (except `.env.example`), `token.json`,
`*.token.json`, `.yahoo_token.json`, `credentials*.json`, `client_secret*.json`,
`*.pem`, and `*.key`. `.env.example` is committed and contains only blank or
inert placeholder values — no client ID, client secret, token, or
authorization code has been committed to this repository.

`scripts/secret_scan.py` scans tracked files against a set of secret patterns
and reports **filenames and categories only**, never values, so its output is
safe to paste into CI logs or a review. It runs on every CI job.

This matters because a prior unrelated archive in this problem space shipped
with a committed token file containing access/refresh-token-shaped fields. The
design here — one token file, outside the repo, encrypted on Windows, ignored
by Git, credentials only from the environment — exists so that class of leak
cannot recur.

## Reporting

If you find a real credential committed anywhere in this project's history,
treat it as compromised: rotate it at the provider (Yahoo app settings), then
report it privately rather than filing a public issue with the value in it.
