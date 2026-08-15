# Security notes

## Token handling

- The OAuth token pair lives in exactly one place: the file at
  `YAHOO_FANTASY_MCP_TOKEN_PATH` (default `~/.config/yahoo-fantasy-mcp/token.json`),
  written via an atomic replace so a crash mid-write cannot leave a
  half-written token file (`auth/token_vault.py`).
- The vault requests `0600` permissions on that file and repairs
  overly-permissive modes on load. **This is a POSIX guarantee only.** On
  Windows, `os.chmod()` only toggles the read-only attribute — the group/other
  bits are not enforced by the filesystem, so a token file on Windows does
  **not** receive real `0600` protection. On Windows, rely on the user profile
  directory's own ACLs and on not placing the token file in a shared location.
  The corresponding tests are skipped on Windows for exactly this reason.
- The vault stores `access_token`, `refresh_token`, `expires_at`, `scope`,
  `obtained_at`. It does **not** store `client_id`/`client_secret` — those come
  from the environment at process start, so a leaked token file alone cannot
  mint new tokens for the app.
- The MCP client config (e.g. Claude Desktop's `claude_desktop_config.json`)
  never contains a token or a client secret. It only points at this process
  and, optionally, the `YAHOO_FANTASY_MCP_TOKEN_PATH`/`.env` location.
- Only `fspt-r` (read-only) scope is ever requested. See
  `auth/oauth_client.py` and `THREAT_MODEL.md`.

## Logging

All structured log **context** payloads go through `logging_utils.redact()`,
which replaces values whose key matches
`access_token|refresh_token|client_secret|authorization|password` and masks
`Bearer ...` substrings inside string values.

Be clear about the limits of that:

- It covers the structured context dict passed through `log_context()`. It does
  **not** rewrite the free-text log message itself.
- It matches a fixed key list plus one bearer-token pattern. It is not general
  secret detection, and it is not comprehensive redaction.

It is defense in depth on top of the actual control, which is not logging token
material in the first place: `yahoo/client.py` never logs a response body on
the success path, and error bodies are capped and are Yahoo error text rather
than token material.

## Keeping credentials out of Git

`.gitignore` blocks `.env`, `token.json`, `*.token.json`, `.yahoo_token.json`,
`*.pem`, and `*.key`. `.env.example` is committed and contains only blank or
inert placeholder values — no client ID, client secret, token, or
authorization code has been committed to this repository.

This matters because a prior unrelated archive in this problem space shipped
with a committed token file containing access/refresh-token-shaped fields. The
design here — one token file, outside the repo, atomic writes, ignored by Git,
credentials only from the environment — exists so that class of leak cannot
recur here.

## Reporting

If you find a real credential committed anywhere in this project's history,
treat it as compromised: rotate it at the provider (Yahoo app settings), then
report it privately rather than filing a public issue with the value in it.
