# Security notes

## Token handling

- The OAuth token pair lives in exactly one place: the file at
  `YAHOO_FANTASY_MCP_TOKEN_PATH` (default `~/.config/yahoo-fantasy-mcp/token.json`),
  written with `0600` permissions via an atomic replace
  (`auth/token_vault.py`). `TokenVault.load()` repairs overly-permissive
  file modes rather than trusting them.
- The vault stores `access_token`, `refresh_token`, `expires_at`, `scope`,
  `obtained_at`. It does **not** store `client_id`/`client_secret` -- those
  come from the environment at process start, so a leaked token file alone
  cannot mint new tokens for the app.
- The MCP client config (e.g. Claude Desktop's `claude_desktop_config.json`)
  never contains a token or a client secret. It only points at this process
  and, optionally, `YAHOO_FANTASY_MCP_TOKEN_PATH`/`.env` location.
- Only `fspt-r` (read-only) scope is ever requested. See
  `auth/oauth_client.py` and `THREAT_MODEL.md`.

## Logging

- All structured logs go through `logging_utils.redact()`, which strips any
  key matching `access_token|refresh_token|client_secret|authorization|password`
  and masks `Bearer ...` substrings inside string values. This is defense in
  depth -- the code should also just not log raw token payloads in the first
  place, and it doesn't (`yahoo/client.py` never logs a response body on the
  success path, and error bodies are capped to 300 chars and are Yahoo error
  text, not token material).

## The `.yahoo_token.json` incident this project is downstream of

`VERIFICATION-RUN-NOTES.md` and `MCP-PLAN-AND-CLAUDE-HANDOFF.md` both flag
that a prior archive (`fantasy-football-mcp-public-main`) shipped with a
committed `.yahoo_token.json` containing access/refresh-token-shaped fields.
That file is not present in this repo, `.gitignore` here blocks
`*.token.json` / `token.json` / `.yahoo_token.json` outright, and the vault
design above (one file, outside the repo, 0600, atomic writes) exists
specifically so this class of leak can't recur here.

## Reporting

If you find a real credential committed anywhere in this project's history,
treat it as compromised: rotate it at the provider (Yahoo app settings),
then report it privately rather than filing a public issue with the value
in it.
