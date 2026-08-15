"""File-based OAuth token vault.

Design goals, directly from the deferred-backlog item:

- No credentials in client config. The MCP client config (e.g. Claude
  Desktop's json) only ever points at this process; it never contains a
  token or client secret.
- One file, outside the repo by default (`~/.config/yahoo-fantasy-mcp/`),
  written with `0600` permissions via an atomic replace so a crash mid-write
  cannot leave a half-written token file.
- The vault stores the OAuth token pair and its expiry. It deliberately does
  NOT store client_id/client_secret -- those come from the environment at
  process start, so a leaked token file alone cannot be used to mint new
  tokens for the app.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class TokenVaultError(RuntimeError):
    pass


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
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> StoredToken | None:
        if not self._path.exists():
            return None
        self._check_permissions()
        raw = json.loads(self._path.read_text())
        try:
            return StoredToken(**raw)
        except TypeError as exc:
            raise TokenVaultError(f"Token file at {self._path} is malformed: {exc}") from exc

    def save(self, token: StoredToken) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(token), indent=2, sort_keys=True)

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".token-", suffix=".tmp"
        )
        try:
            os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
        os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)  # 0600, belt and suspenders

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()

    def _check_permissions(self) -> None:
        mode = stat.S_IMODE(os.stat(self._path).st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            # Group/other has some access. Repair rather than silently trust it.
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
