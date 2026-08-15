import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yahoo_fantasy_mcp.logging_utils import redact


def test_redacts_secret_shaped_keys():
    payload = {
        "access_token": "abc123",
        "refresh_token": "def456",
        "client_secret": "shh",
        "safe_field": "keep me",
        "nested": {"password": "hunter2", "ok": 1},
    }
    result = redact(payload)
    assert result["access_token"] == "[REDACTED]"
    assert result["refresh_token"] == "[REDACTED]"
    assert result["client_secret"] == "[REDACTED]"
    assert result["safe_field"] == "keep me"
    assert result["nested"]["password"] == "[REDACTED]"
    assert result["nested"]["ok"] == 1


def test_redacts_bearer_token_in_strings():
    payload = {"header": "Authorization: Bearer abcDEF123.456-_~+/="}
    result = redact(payload)
    assert "abcDEF123" not in result["header"]
    assert "Bearer [REDACTED]" in result["header"]


def test_redacts_inside_lists():
    payload = [{"access_token": "x"}, {"safe": "y"}]
    result = redact(payload)
    assert result[0]["access_token"] == "[REDACTED]"
    assert result[1]["safe"] == "y"
