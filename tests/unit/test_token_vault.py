import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yahoo_fantasy_mcp.auth.token_vault import StoredToken, TokenVault, TokenVaultError


def _token(expires_in=3600):
    now = time.time()
    return StoredToken(
        access_token="secret-access",
        refresh_token="secret-refresh",
        expires_at=now + expires_in,
        scope="fspt-r",
        obtained_at=now,
    )


def test_save_then_load_round_trips(tmp_path):
    vault = TokenVault(tmp_path / "sub" / "token.json")
    token = _token()
    vault.save(token)

    loaded = vault.load()
    assert loaded == token


def test_save_writes_with_0600_permissions(tmp_path):
    vault = TokenVault(tmp_path / "token.json")
    vault.save(_token())

    mode = stat.S_IMODE((tmp_path / "token.json").stat().st_mode)
    assert mode == 0o600


def test_load_missing_file_returns_none(tmp_path):
    vault = TokenVault(tmp_path / "does_not_exist.json")
    assert vault.load() is None


def test_load_repairs_overly_permissive_file(tmp_path):
    path = tmp_path / "token.json"
    vault = TokenVault(path)
    vault.save(_token())
    path.chmod(0o644)

    vault.load()  # should repair, not raise

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_malformed_token_file_raises_vault_error(tmp_path):
    path = tmp_path / "token.json"
    path.write_text('{"unexpected_field": true}')
    path.chmod(0o600)
    vault = TokenVault(path)

    try:
        vault.load()
        assert False, "expected TokenVaultError"
    except TokenVaultError:
        pass


def test_is_expired_true_when_past_expiry():
    expired = _token(expires_in=-10)
    assert expired.is_expired is True

    fresh = _token(expires_in=3600)
    assert fresh.is_expired is False


def test_redacted_never_exposes_raw_tokens():
    token = _token()
    redacted = token.redacted()
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["refresh_token"] == "[REDACTED]"
    assert "secret-access" not in str(redacted)
    assert "secret-refresh" not in str(redacted)


def test_clear_removes_file(tmp_path):
    vault = TokenVault(tmp_path / "token.json")
    vault.save(_token())
    assert vault.exists()
    vault.clear()
    assert not vault.exists()
