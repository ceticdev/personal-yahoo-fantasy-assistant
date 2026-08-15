#!/usr/bin/env python3
"""One-time interactive OAuth flow. Run this once, then the server refreshes
the token automatically. Prints nothing secret to the terminal -- only a
redacted confirmation.

Requires YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET in the environment (load them
from .env yourself, e.g. `set -a && source .env && set +a` on Linux/macOS,
or `Get-Content .env | ForEach-Object { ... }` on Windows).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yahoo_fantasy_mcp.auth.oauth_client import YahooOAuthClient  # noqa: E402
from yahoo_fantasy_mcp.auth.token_vault import TokenVault  # noqa: E402
from yahoo_fantasy_mcp.config import load_config  # noqa: E402


def main() -> None:
    config = load_config()
    if not config.has_credentials:
        print(
            "YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET are not set in the environment. "
            "Fill in .env (see .env.example) and load it into this shell first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    vault = TokenVault(config.token_path)
    client = YahooOAuthClient(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=config.redirect_uri,
        vault=vault,
    )

    print("This grants READ-ONLY access (scope=fspt-r). Open this URL and approve it:\n")
    print(client.authorization_url())
    print(
        "\nYahoo will show you a verifier code (redirect_uri=oob) or redirect with "
        "?code=... if you configured a real redirect URI."
    )
    code = input("\nPaste the code here: ").strip()
    if not code:
        print("No code entered, aborting.", file=sys.stderr)
        raise SystemExit(1)

    token = client.exchange_code(code)
    print(f"\nToken saved to {vault.path} (0600 permissions).")
    print(f"Redacted state: {token.redacted()}")


if __name__ == "__main__":
    main()
