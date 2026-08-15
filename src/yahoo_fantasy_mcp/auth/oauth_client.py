"""Yahoo OAuth2 client: authorization-code flow + refresh, read-only scope only.

Yahoo's Fantasy Sports API uses two OAuth scope keywords: `fspt-r` (read) and
`fspt-w` (write). This client hard-codes `fspt-r`. There is no code path in
this package that requests write scope -- adding one is an explicit,
separate decision gated by `docs/THREAT_MODEL.md`, not a config flag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import READ_ONLY_SCOPE
from ..errors import (
    OAuthTransportError,
    TokenMissingError,
    TokenRefreshError,
    YahooMcpError,
    truncate_provider_body,
)
from ..logging_utils import register_secret
from .token_vault import StoredToken, TokenVault

AUTHORIZATION_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


class OAuthError(TokenRefreshError):
    """Backwards-compatible name for an OAuth-layer failure.

    Subclasses TokenRefreshError so an uncaught one still surfaces as a typed,
    auth_required envelope rather than an internal error.
    """


@dataclass(frozen=True, slots=True)
class YahooOAuthClient:
    client_id: str
    client_secret: str
    redirect_uri: str
    vault: TokenVault
    scope: str = READ_ONLY_SCOPE

    def authorization_url(self) -> str:
        """URL the operator opens in a browser to grant read-only access."""

        params = httpx.QueryParams(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": self.scope,
                "language": "en-us",
            }
        )
        return f"{AUTHORIZATION_URL}?{params}"

    def exchange_code(self, authorization_code: str) -> StoredToken:
        """One-time exchange of an authorization code for a token pair."""

        response = self._post_token(
            {
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": authorization_code,
            }
        )
        token = self._store_response(response)
        self.vault.save(token)
        return token

    def refresh(self, current: StoredToken) -> StoredToken:
        response = self._post_token(
            {
                "grant_type": "refresh_token",
                "redirect_uri": self.redirect_uri,
                "refresh_token": current.refresh_token,
            }
        )
        token = self._store_response(response, fallback_refresh_token=current.refresh_token)
        self.vault.save(token)
        return token

    def get_valid_token(self) -> StoredToken:
        """Load the vaulted token, refreshing it first if it is expired."""

        current = self.vault.load()
        if current is None:
            raise TokenMissingError(
                "No Yahoo token is vaulted. Run scripts/obtain_yahoo_token.py once "
                "to complete the interactive read-only OAuth flow."
            )
        if current.is_expired:
            try:
                return self.refresh(current)
            except YahooMcpError:
                raise
            except Exception as exc:  # defensive: never leak a raw exception
                raise TokenRefreshError(
                    f"Refreshing the Yahoo token failed: {type(exc).__name__}"
                ) from exc
        return current

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        register_secret(self.client_secret)
        auth = (self.client_id, self.client_secret)
        # The ONLY POST this package makes, and only ever to Yahoo's token
        # endpoint. See tests/contract/test_read_only_transport.py.
        try:
            response = httpx.post(TOKEN_URL, data=data, auth=auth, timeout=15.0)
        except httpx.HTTPError as exc:
            raise OAuthTransportError(
                f"Yahoo token endpoint unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            # Yahoo error bodies are capped and scrubbed before they go anywhere.
            raise TokenRefreshError(
                f"Yahoo token endpoint returned {response.status_code}: "
                f"{truncate_provider_body(response.text)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise TokenRefreshError(
                "Yahoo token endpoint returned a non-JSON body"
            ) from exc

    def _store_response(
        self, response: dict[str, Any], fallback_refresh_token: str | None = None
    ) -> StoredToken:
        access_token = response.get("access_token")
        refresh_token = response.get("refresh_token") or fallback_refresh_token
        expires_in = response.get("expires_in", 3600)
        granted_scope = response.get("xoauth_yahoo_guid_scope") or response.get(
            "scope", self.scope
        )
        if not access_token or not refresh_token:
            raise TokenRefreshError(
                "Yahoo token response is missing access_token/refresh_token"
            )
        # Register before the values can reach any log line.
        register_secret(access_token)
        register_secret(refresh_token)
        if self.scope not in str(granted_scope) and granted_scope != self.scope:
            # Non-fatal: Yahoo does not always echo scope back identically.
            # Record what we asked for, since that is what governs behavior here.
            granted_scope = self.scope
        now = time.time()
        return StoredToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + float(expires_in),
            scope=str(granted_scope),
            obtained_at=now,
        )
