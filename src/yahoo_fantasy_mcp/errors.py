"""Typed, envelope-shaped errors for every expected runtime failure.

Every failure an operator can actually hit -- no credentials, no token, a
corrupt token file, an unreadable token file, a refresh that fails, Yahoo
unreachable, Yahoo 401, Yahoo's provisioning 403 -- is represented here as a
typed exception carrying the four flags a caller needs to decide what to do:

    auth_required     the operator has to do something with credentials/token
    not_provisioned   Yahoo has not granted API access to this app yet
    retryable         a later identical call could plausibly succeed
    error_type        a stable machine-readable discriminator

MCP tools convert these into `error_envelope()` results rather than letting
them escape as uncaught FastMCP ToolErrors. Programming errors (a parser bug,
a bad argument) deliberately do NOT live here -- they are not expected
operational states and must not be laundered into a friendly envelope.
"""

from __future__ import annotations

from typing import Any

from .logging_utils import scrub_text

# Provider response bodies are never embedded verbatim or uncapped.
MAX_PROVIDER_BODY_CHARS = 200


class YahooMcpError(RuntimeError):
    """Base class for expected, operator-actionable runtime failures."""

    error_type = "internal_error"
    auth_required = False
    not_provisioned = False
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(scrub_text(message))

    def as_envelope(self, **extra: Any) -> dict[str, Any]:
        return error_envelope(self, **extra)


# -- Credential / vault failures ------------------------------------------


class CredentialsMissingError(YahooMcpError):
    error_type = "credentials_missing"
    auth_required = True


class TokenMissingError(YahooMcpError):
    error_type = "token_missing"
    auth_required = True


class TokenMalformedError(YahooMcpError):
    error_type = "token_malformed"
    auth_required = True


class TokenAccessError(YahooMcpError):
    """Token file exists but could not be read/written (permissions, I/O, DPAPI)."""

    error_type = "token_access_failed"
    auth_required = True


class TokenProtectionError(YahooMcpError):
    """Platform token protection (e.g. Windows DPAPI) is unavailable or failed.

    This is fail-closed: we raise rather than fall back to a plaintext token.
    """

    error_type = "token_protection_unavailable"
    auth_required = True


# -- OAuth failures --------------------------------------------------------


class TokenRefreshError(YahooMcpError):
    error_type = "token_refresh_failed"
    auth_required = True


class OAuthTransportError(YahooMcpError):
    error_type = "oauth_transport_failed"
    retryable = True


# -- Yahoo API failures ----------------------------------------------------


class YahooApiError(YahooMcpError):
    """Generic Yahoo API failure. Kept as the broad catch for API-layer errors."""

    error_type = "yahoo_api_error"

    def __init__(self, message: str, *, not_provisioned: bool = False) -> None:
        super().__init__(message)
        if not_provisioned:
            # Preserved for callers constructing this directly.
            self.not_provisioned = True
            self.error_type = "yahoo_not_provisioned"


class YahooTransportError(YahooApiError):
    """Yahoo unreachable: DNS, connect, read timeout, TLS. Worth retrying."""

    error_type = "yahoo_transport_failed"
    retryable = True


class YahooServiceError(YahooApiError):
    """Yahoo answered with 5xx/429. Worth retrying."""

    error_type = "yahoo_service_error"
    retryable = True


class YahooUnauthorizedError(YahooApiError):
    """Yahoo rejected the token (401)."""

    error_type = "yahoo_unauthorized"
    auth_required = True


class YahooNotProvisionedError(YahooApiError):
    """Yahoo has not provisioned API access for this app yet (403)."""

    error_type = "yahoo_not_provisioned"
    not_provisioned = True


#: Failures that represent an upstream/transport problem rather than a bug or
#: an auth problem. Only these are eligible for serving stale cached data.
STALE_FALLBACK_ELIGIBLE: tuple[type[YahooMcpError], ...] = (
    YahooTransportError,
    YahooServiceError,
)


def truncate_provider_body(body: str | None, limit: int = MAX_PROVIDER_BODY_CHARS) -> str:
    """Cap and scrub a provider response body before it goes anywhere."""

    if not body:
        return ""
    text = scrub_text(str(body))
    if len(text) > limit:
        return text[:limit] + f"... [truncated, {limit} char cap]"
    return text


def error_envelope(exc: BaseException, **extra: Any) -> dict[str, Any]:
    """The single structured error shape every MCP tool returns on failure.

    Unknown exception types degrade to a generic, non-retryable internal
    error whose message is scrubbed -- we never leak a raw traceback or an
    arbitrary exception payload to the client.
    """

    if isinstance(exc, YahooMcpError):
        envelope = {
            "error": scrub_text(str(exc)),
            "error_type": exc.error_type,
            "auth_required": exc.auth_required,
            "not_provisioned": exc.not_provisioned,
            "retryable": exc.retryable,
            "data": None,
        }
    else:
        envelope = {
            "error": scrub_text(f"{type(exc).__name__}: {exc}"),
            "error_type": "internal_error",
            "auth_required": False,
            "not_provisioned": False,
            "retryable": False,
            "data": None,
        }
    envelope.update(extra)
    return envelope
