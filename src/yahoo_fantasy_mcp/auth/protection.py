"""Platform token-at-rest protection.

Two strategies, selected by platform:

* **POSIX** (`PosixFileProtector`): the token JSON is written as-is and the
  file carries `0600`, enforced by the filesystem. This is the historical
  behavior and is unchanged.

* **Windows** (`DpapiProtector`): the token JSON is encrypted with the Windows
  Data Protection API (`CryptProtectData`) bound to the *current Windows
  user*, then written as a small JSON envelope. Windows does not enforce POSIX
  mode bits -- `os.chmod` there only toggles the read-only attribute -- so
  file permissions alone would leave the token pair readable as plaintext by
  anything running as that account or able to read the file. DPAPI was chosen
  over Credential Manager because it needs no third-party dependency (it is a
  `ctypes` call into `crypt32.dll`), stores arbitrary-length blobs without the
  2560-byte credential-blob limit, and keeps the "one file, atomically
  replaced" model the rest of this package is built around. It was chosen over
  a hand-rolled ACL because an ACL still leaves plaintext on disk.

Both paths **fail closed**. If DPAPI is unavailable or a protect/unprotect
call fails, we raise `TokenProtectionError` -- we never degrade to writing a
plaintext token on Windows.

Storage format
--------------

POSIX (`format: "plaintext-v1"` implied -- the file is the token JSON itself)::

    {"access_token": "...", "refresh_token": "...", ...}

Windows::

    {"format": "dpapi-v1", "platform": "win32", "ciphertext": "<base64>"}

Migration: a Windows vault that finds a legacy plaintext token file reads it,
immediately rewrites it in DPAPI form, and continues. See `docs/SECURITY.md`.
"""

from __future__ import annotations

import base64
import ctypes
import json
import sys
from typing import Any, Protocol

from ..errors import TokenMalformedError, TokenProtectionError

DPAPI_FORMAT = "dpapi-v1"
DPAPI_DESCRIPTION = "yahoo-fantasy-mcp OAuth token"


class TokenProtector(Protocol):
    """Serializes a token payload to bytes on disk and back."""

    name: str

    def protect(self, payload: dict[str, Any]) -> bytes: ...

    def unprotect(self, blob: bytes) -> dict[str, Any]: ...


def _decode_json(blob: bytes) -> dict[str, Any]:
    try:
        return json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenMalformedError(f"Token file is not valid JSON: {exc}") from exc


class PosixFileProtector:
    """Plaintext JSON on disk, protected by `0600` file permissions."""

    name = "posix-0600"

    def protect(self, payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

    def unprotect(self, blob: bytes) -> dict[str, Any]:
        data = _decode_json(blob)
        if data.get("format") == DPAPI_FORMAT:
            raise TokenProtectionError(
                "This token file is DPAPI-encrypted and can only be read on the "
                "Windows user account that created it. Re-run "
                "scripts/obtain_yahoo_token.py on this machine to create a new one."
            )
        return data


# --- Windows DPAPI ---------------------------------------------------------


# ctypes.wintypes cannot even be imported on non-Windows, so the structure is
# defined lazily. Everything above this point must stay importable everywhere.
def _data_blob_type():
    from ctypes import wintypes  # noqa: PLC0415 - Windows-only import by design

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    return _DataBlob


def _blob_to_bytes(blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free_blob(blob) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)  # type: ignore[attr-defined]


def dpapi_available() -> bool:
    """True only on Windows with crypt32 loadable."""

    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.crypt32  # type: ignore[attr-defined]
    except (AttributeError, OSError):  # pragma: no cover - exercised via mocks
        return False
    return True


def dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes with CryptProtectData, bound to the current Windows user."""

    if not dpapi_available():  # pragma: no cover - exercised via mocks
        raise TokenProtectionError(
            "Windows DPAPI (crypt32) is unavailable, so the token cannot be "
            "encrypted at rest. Refusing to write a plaintext token."
        )
    blob_type = _data_blob_type()
    source = blob_type(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    result = blob_type()
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(source),
        ctypes.c_wchar_p(DPAPI_DESCRIPTION),
        None,
        None,
        None,
        0,
        ctypes.byref(result),
    )
    if not ok:  # pragma: no cover - exercised via mocks
        raise TokenProtectionError(
            f"Windows DPAPI CryptProtectData failed (error {ctypes.GetLastError()}). "
            "Refusing to write a plaintext token."
        )
    try:
        return _blob_to_bytes(result)
    finally:
        _free_blob(result)


def dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt bytes previously produced by `dpapi_protect` on this account."""

    if not dpapi_available():  # pragma: no cover - exercised via mocks
        raise TokenProtectionError(
            "Windows DPAPI (crypt32) is unavailable, so the encrypted token "
            "cannot be read."
        )
    blob_type = _data_blob_type()
    source = blob_type(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    result = blob_type()
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(result),
    )
    if not ok:  # pragma: no cover - exercised via mocks
        raise TokenProtectionError(
            f"Windows DPAPI CryptUnprotectData failed (error {ctypes.GetLastError()}). "
            "The token file was most likely created by a different Windows user "
            "or on a different machine. Re-run scripts/obtain_yahoo_token.py."
        )
    try:
        return _blob_to_bytes(result)
    finally:
        _free_blob(result)


class DpapiProtector:
    """DPAPI-encrypted token storage for Windows. Fails closed."""

    name = "windows-dpapi"

    def __init__(self, protect_fn=dpapi_protect, unprotect_fn=dpapi_unprotect) -> None:
        # Injectable so the Windows path can be tested with mocks on any OS.
        self._protect = protect_fn
        self._unprotect = unprotect_fn

    def protect(self, payload: dict[str, Any]) -> bytes:
        plaintext = json.dumps(payload, sort_keys=True).encode("utf-8")
        ciphertext = self._protect(plaintext)
        if not ciphertext:
            raise TokenProtectionError(
                "Windows DPAPI returned an empty ciphertext. Refusing to write "
                "a plaintext token."
            )
        envelope = {
            "format": DPAPI_FORMAT,
            "platform": "win32",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        return json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")

    def unprotect(self, blob: bytes) -> dict[str, Any]:
        envelope = _decode_json(blob)

        if envelope.get("format") != DPAPI_FORMAT:
            # Legacy plaintext token from before Windows protection existed.
            # The vault detects this and re-saves it encrypted (migration).
            if "access_token" in envelope:
                return envelope
            raise TokenMalformedError(
                "Token file is neither a DPAPI envelope nor a recognizable token."
            )

        raw = envelope.get("ciphertext")
        if not isinstance(raw, str) or not raw:
            raise TokenMalformedError("DPAPI token envelope has no ciphertext.")
        try:
            ciphertext = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as exc:
            raise TokenMalformedError(f"DPAPI token ciphertext is not valid base64: {exc}") from exc

        return _decode_json(self._unprotect(ciphertext))


def default_protector() -> TokenProtector:
    """Pick the protector for this platform. Windows never gets plaintext."""

    if sys.platform == "win32":
        return DpapiProtector()
    return PosixFileProtector()


def is_dpapi_envelope(blob: bytes) -> bool:
    """True if the bytes look like a DPAPI envelope (used for migration checks)."""

    try:
        return json.loads(blob.decode("utf-8")).get("format") == DPAPI_FORMAT
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False
