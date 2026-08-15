"""File-based OAuth token vault with platform-appropriate protection at rest.

Design goals:

- No credentials in client config. The MCP client config (e.g. Claude
  Desktop's json) only ever points at this process; it never contains a
  token or client secret.
- One file, outside the repo by default (`~/.config/yahoo-fantasy-mcp/`),
  written via an atomic replace so a crash mid-write cannot leave a
  half-written token file.
- **POSIX:** the file is the token JSON, protected by `0600`, enforced by the
  filesystem. Loose modes are repaired on load.
- **Windows:** POSIX mode bits are not enforced, so instead the token JSON is
  encrypted with DPAPI bound to the current Windows user before it is written
  (`auth/protection.py`). This **fails closed** -- if DPAPI is unavailable or
  fails, the save raises rather than writing a plaintext token. A legacy
  plaintext token file found on Windows is migrated to the encrypted form on
  first load.
- The vault stores the OAuth token pair and its expiry. It deliberately does
  NOT store client_id/client_secret -- those come from the environment at
  process start, so a leaked token file alone cannot be used to mint new
  tokens for the app.
- Every failure mode raises a typed error from `errors.py` so MCP tools can
  return a structured envelope instead of an uncaught exception.

See `docs/SECURITY.md` for storage format, migration, recovery, and how to
revoke or clear the token.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..errors import (
    TokenAccessError,
    TokenMalformedError,
    TokenMissingError,
    TokenProtectionError,
)
from ..logging_utils import register_secret
from .protection import (
    DpapiProtector,
    TokenProtector,
    default_protector,
    is_dpapi_envelope,
)


class TokenVaultError(TokenAccessError):
    """Backwards-compatible alias for a vault-level failure."""

    error_type = "token_vault_error"


@dataclass(frozen=True, slots=True)
class StoredToken:
    access_token: str
    refresh_token: str
    expires_at: float  # unix epoch seconds
    scope: str
    obtained_at: float

    @property
    def is_expired(self) -> bool:
        # 60s safety margin so a call doesn't start with a token that expires
        # mid-request.
        return time.time() >= (self.expires_at - 60)

    def redacted(self) -> dict[str, Any]:
        return {
            "access_token": "[REDACTED]",
            "refresh_token": "[REDACTED]",
            "expires_at": self.expires_at,
            "scope": self.scope,
            "obtained_at": self.obtained_at,
            "expired": self.is_expired,
        }


class TokenVault:
    def __init__(self, path: Path, protector: TokenProtector | None = None) -> None:
        self._path = path
        self._protector = protector if protector is not None else default_protector()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def protection(self) -> str:
        """Name of the at-rest protection in force, for status output."""

        return self._protector.name

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> StoredToken | None:
        """Return the stored token, or None if no token file exists.

        Raises `TokenMalformedError` for unparseable content,
        `TokenAccessError` for I/O or permission failures, and
        `TokenProtectionError` if platform decryption is unavailable/failed.
        """

        if not self._path.exists():
            return None

        self._check_permissions()

        try:
            blob = self._path.read_bytes()
        except OSError as exc:
            raise TokenAccessError(
                f"Token file at {self._path} could not be read: {exc.__class__.__name__}"
            ) from exc

        payload = self._protector.unprotect(blob)

        try:
            token = StoredToken(**payload)
        except TypeError as exc:
            raise TokenMalformedError(f"Token file at {self._path} is malformed: {exc}") from exc

        self._register_secrets(token)

        # Migration: a Windows vault that just read a legacy plaintext token
        # rewrites it encrypted immediately, so the plaintext stops existing.
        if isinstance(self._protector, DpapiProtector) and not is_dpapi_envelope(blob):
            self.save(token)

        return token

    def require(self) -> StoredToken:
        """Like `load()`, but raises `TokenMissingError` when there is no token."""

        token = self.load()
        if token is None:
            raise TokenMissingError(
                "No Yahoo token is vaulted. Run scripts/obtain_yahoo_token.py once "
                "to complete the interactive read-only OAuth flow."
            )
        return token

    def save(self, token: StoredToken) -> None:
        """Atomically write the token, protected appropriately for this platform.

        Fails closed: if protection fails, nothing is written.
        """

        self._register_secrets(token)

        # Protect FIRST. If this raises, no file is touched -- in particular a
        # Windows DPAPI failure never leaves a plaintext token behind.
        blob = self._protector.protect(asdict(token))

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".token-", suffix=".tmp"
            )
        except OSError as exc:
            raise TokenAccessError(
                f"Could not create the token file at {self._path}: {exc.__class__.__name__}"
            ) from exc

        try:
            os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)  # 0600 (enforced on POSIX)
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except OSError as exc:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise TokenAccessError(
                f"Could not write the token file at {self._path}: {exc.__class__.__name__}"
            ) from exc
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)  # 0600, belt and suspenders
        except OSError:  # pragma: no cover - best effort, POSIX already covered above
            pass

    def clear(self) -> None:
        """Delete the token file. This is the local half of revoking access."""

        try:
            if self._path.exists():
                self._path.unlink()
        except OSError as exc:
            raise TokenAccessError(
                f"Could not remove the token file at {self._path}: {exc.__class__.__name__}"
            ) from exc

    def status(self) -> dict[str, Any]:
        """Structured, never-raising diagnostic for `token_vault_status`."""

        from ..errors import error_envelope, YahooMcpError

        base: dict[str, Any] = {
            "vault_path": str(self._path),
            "protection": self.protection,
            "platform": sys.platform,
            "token_present": False,
            "token": None,
        }
        try:
            token = self.load()
        except YahooMcpError as exc:
            base.update(error_envelope(exc))
            base["data"] = None
            return base
        base["token_present"] = token is not None
        base["token"] = token.redacted() if token else None
        return base

    @staticmethod
    def _register_secrets(token: StoredToken) -> None:
        register_secret(token.access_token)
        register_secret(token.refresh_token)

    def _check_permissions(self) -> None:
        """Repair group/other-readable modes on POSIX.

        On Windows this is a no-op by design: `os.chmod` there only toggles the
        read-only attribute, so confidentiality comes from DPAPI encryption
        instead of from mode bits.
        """

        if sys.platform == "win32":
            return
        try:
            mode = stat.S_IMODE(os.stat(self._path).st_mode)
        except OSError as exc:
            raise TokenAccessError(
                f"Token file at {self._path} could not be stat'ed: {exc.__class__.__name__}"
            ) from exc
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            # Group/other has some access. Repair rather than silently trust it.
            try:
                os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                raise TokenAccessError(
                    f"Token file at {self._path} has unsafe permissions that could "
                    f"not be repaired: {exc.__class__.__name__}"
                ) from exc


__all__ = [
    "StoredToken",
    "TokenVault",
    "TokenVaultError",
    "TokenMalformedError",
    "TokenMissingError",
    "TokenProtectionError",
]
