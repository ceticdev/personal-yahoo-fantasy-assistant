"""The release archive check actually rejects what it claims to reject.

A verifier that never fails is worse than no verifier, so these tests build
synthetic archives containing each forbidden category and assert the checker
catches them -- rather than only asserting that a known-good archive passes.
"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest

from make_release import FORBIDDEN_PATTERNS, PROJECT_NAME, REQUIRED_ENTRIES, sha256, verify

GOOD_ENTRIES = [
    f"{PROJECT_NAME}/README.md",
    f"{PROJECT_NAME}/pyproject.toml",
    f"{PROJECT_NAME}/.env.example",
    f"{PROJECT_NAME}/src/yahoo_fantasy_mcp/server.py",
    f"{PROJECT_NAME}/tests/fixtures/roster_sample.json",
]


def _archive(tmp_path: Path, names: list[str], name: str = "release.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for entry in names:
            zf.writestr(entry, "x")
    return path


def test_a_clean_archive_passes(tmp_path):
    ok, problems = verify(_archive(tmp_path, GOOD_ENTRIES))
    assert ok, problems


@pytest.mark.parametrize(
    "polluted_entry",
    [
        f"{PROJECT_NAME}/.git/config",
        f"{PROJECT_NAME}/.venv/lib/site-packages/httpx/__init__.py",
        f"{PROJECT_NAME}/.pytest_cache/CACHEDIR.TAG",
        f"{PROJECT_NAME}/src/yahoo_fantasy_mcp/__pycache__/server.cpython-311.pyc",
        f"{PROJECT_NAME}/src/yahoo_fantasy_mcp/server.pyc",
        f"{PROJECT_NAME}/src/yahoo_fantasy_mcp_v2.egg-info/PKG-INFO",
        f"{PROJECT_NAME}/.env",
        f"{PROJECT_NAME}/.env.local",
        f"{PROJECT_NAME}/token.json",
        f"{PROJECT_NAME}/.yahoo_token.json",
        f"{PROJECT_NAME}/credentials.json",
        f"{PROJECT_NAME}/client_secret_123.json",
        f"{PROJECT_NAME}/server.pem",
        f"{PROJECT_NAME}/private.key",
        f"{PROJECT_NAME}/reports/local-run.md",
        f"{PROJECT_NAME}/MCP-PLAN-AND-CLAUDE-HANDOFF.md",
        f"{PROJECT_NAME}/deliverable/VERIFICATION-RUN-NOTES.md",
        f"{PROJECT_NAME}/.serena/project.yml",
    ],
)
def test_each_forbidden_category_is_rejected(tmp_path, polluted_entry):
    ok, problems = verify(_archive(tmp_path, GOOD_ENTRIES + [polluted_entry]))

    assert not ok
    assert any(polluted_entry in problem for problem in problems)


def test_env_example_itself_is_allowed(tmp_path):
    """The dotenv rule must not catch the documentation file we ship."""

    ok, problems = verify(_archive(tmp_path, GOOD_ENTRIES))
    assert ok, problems
    assert any(".env.example" in entry for entry in GOOD_ENTRIES)


def test_multiple_top_level_directories_are_rejected(tmp_path):
    ok, problems = verify(_archive(tmp_path, GOOD_ENTRIES + ["other-project/README.md"]))

    assert not ok
    assert any("top-level" in problem for problem in problems)


@pytest.mark.parametrize("required", REQUIRED_ENTRIES)
def test_missing_required_entries_are_rejected(tmp_path, required):
    remaining = [entry for entry in GOOD_ENTRIES if not entry.endswith(f"/{required}")]
    ok, problems = verify(_archive(tmp_path, remaining))

    assert not ok
    assert any(required in problem for problem in problems)


def test_empty_archive_is_rejected(tmp_path):
    ok, problems = verify(_archive(tmp_path, []))
    assert not ok
    assert problems


def test_sha256_is_stable_and_hex(tmp_path):
    archive = _archive(tmp_path, GOOD_ENTRIES)
    digest = sha256(archive)

    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert digest == sha256(archive)


def test_every_documented_category_has_a_pattern():
    expected = {
        "git metadata",
        "virtualenv",
        "pytest cache",
        "bytecode cache",
        "compiled bytecode",
        "egg-info",
        "dotenv secrets",
        "token file",
        "credential file",
        "key material",
        "local reports",
        "parent NFL folder documents",
    }
    assert expected <= set(FORBIDDEN_PATTERNS)


def test_secret_scanner_reports_categories_without_values(tmp_path, monkeypatch):
    """The scanner must find a planted secret and never echo it."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from secret_scan import scan

    planted = tmp_path / "leaky.py"
    planted.write_text('client_secret = "abcdef0123456789abcdef"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    scanned, hits = scan(["leaky.py"])

    assert scanned == 1
    assert "leaky.py" in hits
    assert "client_secret_value" in hits["leaky.py"]
    # The report carries categories, not values.
    assert all("abcdef0123456789" not in category for category in hits["leaky.py"])


def test_secret_scanner_is_clean_on_a_benign_file(tmp_path, monkeypatch):
    benign = tmp_path / "ok.py"
    benign.write_text('LEAGUE_KEY = "999.l.100000"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from secret_scan import scan

    scanned, hits = scan(["ok.py"])

    assert scanned == 1
    assert hits == {}
