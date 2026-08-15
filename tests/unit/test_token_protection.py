"""Windows token-at-rest protection, exercised on any OS via injected mocks.

The production machine is Windows, where POSIX mode bits are not enforced, so
the token pair is DPAPI-encrypted instead. These tests never require the
runner to be Windows: `DpapiProtector` takes its protect/unprotect callables
as arguments, so a fake DPAPI can stand in everywhere.

The properties that matter, and are asserted below:

* a DPAPI-protected token file contains no plaintext token material;
* it round-trips back to the same token;
* if DPAPI fails, the save **fails closed** -- it raises and writes nothing,
  and in particular never falls back to plaintext;
* a legacy plaintext token file is migrated to the encrypted form on load;
* a file encrypted for another Windows user surfaces a typed, actionable error.
"""

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.auth.protection import (
    DPAPI_FORMAT,
    DpapiProtector,
    PosixFileProtector,
    default_protector,
    is_dpapi_envelope,
)
from yahoo_fantasy_mcp.auth.token_vault import StoredToken, TokenVault
from yahoo_fantasy_mcp.errors import (
    TokenMalformedError,
    TokenProtectionError,
)

ACCESS_SENTINEL = "ACCESS-TOKEN-SENTINEL-8f3a1c"
REFRESH_SENTINEL = "REFRESH-TOKEN-SENTINEL-2b9d7e"


def _token() -> StoredToken:
    now = time.time()
    return StoredToken(
        access_token=ACCESS_SENTINEL,
        refresh_token=REFRESH_SENTINEL,
        expires_at=now + 3600,
        scope="fspt-r",
        obtained_at=now,
    )


# A reversible stand-in for CryptProtectData/CryptUnprotectData. Not crypto --
# it exists to prove the vault's plumbing and failure handling, which is the
# part we can test off-Windows.
def _fake_protect(data: bytes) -> bytes:
    return b"DPAPI:" + base64.b64encode(data)


def _fake_unprotect(blob: bytes) -> bytes:
    if not blob.startswith(b"DPAPI:"):
        raise TokenProtectionError("not a fake-DPAPI blob")
    return base64.b64decode(blob[len("DPAPI:") :])


def _fake_dpapi() -> DpapiProtector:
    return DpapiProtector(protect_fn=_fake_protect, unprotect_fn=_fake_unprotect)


def test_windows_token_file_contains_no_plaintext_token(tmp_path):
    vault = TokenVault(tmp_path / "token.json", protector=_fake_dpapi())
    vault.save(_token())

    raw = (tmp_path / "token.json").read_bytes()

    assert ACCESS_SENTINEL.encode() not in raw
    assert REFRESH_SENTINEL.encode() not in raw
    assert json.loads(raw)["format"] == DPAPI_FORMAT
    assert is_dpapi_envelope(raw)


def test_windows_token_round_trips(tmp_path):
    vault = TokenVault(tmp_path / "token.json", protector=_fake_dpapi())
    token = _token()
    vault.save(token)

    assert vault.load() == token


def test_save_fails_closed_when_dpapi_is_unavailable(tmp_path):
    def broken_protect(data: bytes) -> bytes:
        raise TokenProtectionError("CryptProtectData unavailable")

    path = tmp_path / "token.json"
    vault = TokenVault(path, protector=DpapiProtector(protect_fn=broken_protect))

    with pytest.raises(TokenProtectionError):
        vault.save(_token())

    # Fail closed: nothing at all was written, plaintext least of all.
    assert not path.exists()


def test_save_refuses_empty_ciphertext_rather_than_writing_plaintext(tmp_path):
    path = tmp_path / "token.json"
    vault = TokenVault(path, protector=DpapiProtector(protect_fn=lambda data: b""))

    with pytest.raises(TokenProtectionError):
        vault.save(_token())
    assert not path.exists()


def test_no_leftover_temp_file_after_a_failed_protect(tmp_path):
    vault = TokenVault(
        tmp_path / "token.json",
        protector=DpapiProtector(protect_fn=lambda data: (_ for _ in ()).throw(TokenProtectionError("no"))),
    )
    with pytest.raises(TokenProtectionError):
        vault.save(_token())

    assert list(tmp_path.iterdir()) == []


def test_legacy_plaintext_file_is_migrated_to_encrypted_on_load(tmp_path):
    """A pre-hardening Windows install must not keep its plaintext token."""

    path = tmp_path / "token.json"
    token = _token()
    # Simulate the old on-disk form: raw token JSON.
    PosixFileProtector()  # documents what the legacy writer used
    path.write_text(
        json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
                "scope": token.scope,
                "obtained_at": token.obtained_at,
            }
        ),
        encoding="utf-8",
    )
    assert ACCESS_SENTINEL.encode() in path.read_bytes()  # plaintext, before

    vault = TokenVault(path, protector=_fake_dpapi())
    loaded = vault.load()

    assert loaded == token
    raw = path.read_bytes()
    assert ACCESS_SENTINEL.encode() not in raw  # migrated, after
    assert is_dpapi_envelope(raw)


def test_token_from_another_windows_user_reports_a_typed_error(tmp_path):
    def foreign_unprotect(blob: bytes) -> bytes:
        raise TokenProtectionError(
            "CryptUnprotectData failed. The token file was most likely created "
            "by a different Windows user."
        )

    path = tmp_path / "token.json"
    TokenVault(path, protector=_fake_dpapi()).save(_token())

    vault = TokenVault(path, protector=DpapiProtector(unprotect_fn=foreign_unprotect))
    with pytest.raises(TokenProtectionError) as excinfo:
        vault.load()

    assert excinfo.value.auth_required is True
    assert excinfo.value.error_type == "token_protection_unavailable"


def test_corrupt_dpapi_envelope_is_malformed_not_a_crash(tmp_path):
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"format": DPAPI_FORMAT, "ciphertext": "!!!not base64!!!"}), encoding="utf-8")

    with pytest.raises(TokenMalformedError):
        TokenVault(path, protector=_fake_dpapi()).load()


def test_posix_protector_refuses_a_dpapi_file_instead_of_guessing(tmp_path):
    path = tmp_path / "token.json"
    TokenVault(path, protector=_fake_dpapi()).save(_token())

    with pytest.raises(TokenProtectionError):
        TokenVault(path, protector=PosixFileProtector()).load()


def test_default_protector_matches_the_platform():
    protector = default_protector()
    if sys.platform == "win32":
        assert protector.name == "windows-dpapi"
    else:
        assert protector.name == "posix-0600"


@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows-only")
def test_real_dpapi_round_trip_on_windows(tmp_path):
    """On the actual production platform, use the real crypt32 calls."""

    vault = TokenVault(tmp_path / "token.json")
    token = _token()
    vault.save(token)

    raw = (tmp_path / "token.json").read_bytes()
    assert ACCESS_SENTINEL.encode() not in raw
    assert json.loads(raw)["format"] == DPAPI_FORMAT
    assert vault.load() == token
    assert vault.protection == "windows-dpapi"


def test_status_never_leaks_raw_token_values(tmp_path):
    vault = TokenVault(tmp_path / "token.json", protector=_fake_dpapi())
    vault.save(_token())

    status = vault.status()
    rendered = json.dumps(status)

    assert status["token_present"] is True
    assert status["token"]["access_token"] == "[REDACTED]"
    assert status["token"]["refresh_token"] == "[REDACTED]"
    assert ACCESS_SENTINEL not in rendered
    assert REFRESH_SENTINEL not in rendered


def test_status_reports_a_structured_error_for_an_unreadable_token(tmp_path):
    path = tmp_path / "token.json"
    path.write_text("{ this is not json", encoding="utf-8")

    status = TokenVault(path, protector=_fake_dpapi()).status()

    assert status["error_type"] == "token_malformed"
    assert status["auth_required"] is True
    assert status["token_present"] is False


def test_clear_removes_the_token_file(tmp_path):
    """Local half of revoking access."""

    vault = TokenVault(tmp_path / "token.json", protector=_fake_dpapi())
    vault.save(_token())
    assert vault.exists()

    vault.clear()

    assert not vault.exists()
    assert vault.load() is None
