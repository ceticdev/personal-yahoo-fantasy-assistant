"""`.env` discovery and precedence.

Deterministic: every test builds its own throwaway directory tree and points
lookup at it explicitly, so nothing depends on the developer's real `.env`.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.config import load_config
from yahoo_fantasy_mcp.env import ENV_PATH_VAR, find_env_file, load_env

MANAGED_VARS = (
    "YAHOO_CLIENT_ID",
    "YAHOO_CLIENT_SECRET",
    "YAHOO_REDIRECT_URI",
    "YAHOO_FANTASY_MCP_TOKEN_PATH",
    "YAHOO_FANTASY_DEFAULT_LEAGUE_KEY",
    "YAHOO_FANTASY_DEFAULT_TEAM_KEY",
    "YAHOO_FANTASY_MCP_CACHE_TTL_SECONDS",
    "YAHOO_FANTASY_MCP_LOG_LEVEL",
    ENV_PATH_VAR,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test from a known-empty environment for our variables."""

    for name in MANAGED_VARS:
        monkeypatch.delenv(name, raising=False)


def _write_env(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_repository_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_env(repo, "YAHOO_CLIENT_ID=from-dotenv\nYAHOO_FANTASY_DEFAULT_LEAGUE_KEY=999.l.100000\n")
    monkeypatch.chdir(repo)

    loaded = load_env()

    assert loaded == (repo / ".env")
    assert os.environ["YAHOO_CLIENT_ID"] == "from-dotenv"
    assert load_config().default_league_key == "999.l.100000"


def test_real_environment_overrides_dotenv(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_env(repo, "YAHOO_CLIENT_ID=from-dotenv\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("YAHOO_CLIENT_ID", "from-real-environment")

    load_env()

    assert os.environ["YAHOO_CLIENT_ID"] == "from-real-environment"
    assert load_config().client_id == "from-real-environment"


def test_found_from_a_different_working_directory(tmp_path, monkeypatch):
    """The console script is launched from anywhere; lookup walks upward."""

    repo = tmp_path / "repo"
    nested = repo / "deep" / "nested" / "cwd"
    _write_env(repo, "YAHOO_CLIENT_ID=upward-search\n")
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert find_env_file() == (repo / ".env")
    load_env()
    assert os.environ["YAHOO_CLIENT_ID"] == "upward-search"


def test_explicit_env_file_variable_wins(tmp_path, monkeypatch):
    elsewhere = _write_env(tmp_path / "elsewhere", "YAHOO_CLIENT_ID=explicit\n")
    cwd = tmp_path / "cwd"
    _write_env(cwd, "YAHOO_CLIENT_ID=implicit\n")
    monkeypatch.chdir(cwd)
    monkeypatch.setenv(ENV_PATH_VAR, str(elsewhere))

    assert find_env_file() == elsewhere
    load_env()
    assert os.environ["YAHOO_CLIENT_ID"] == "explicit"


def test_missing_env_is_a_silent_no_op(tmp_path, monkeypatch):
    empty = tmp_path / "no_env_anywhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    # Point the anchor search at the empty tree too, so a real repo .env above
    # the temp dir cannot be picked up.
    monkeypatch.setattr("yahoo_fantasy_mcp.env._PACKAGE_ANCHOR", empty / "pkg" / "env.py")

    assert find_env_file() is None
    assert load_env() is None

    config = load_config()
    assert config.client_id is None
    assert config.has_credentials is False
    assert config.env_file is None


def test_env_example_is_never_loaded(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env.example").write_text("YAHOO_CLIENT_ID=placeholder-must-not-load\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr("yahoo_fantasy_mcp.env._PACKAGE_ANCHOR", repo / "pkg" / "env.py")

    assert find_env_file() is None
    assert load_env() is None
    assert "YAHOO_CLIENT_ID" not in os.environ


def test_dotenv_can_be_skipped_entirely(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_env(repo, "YAHOO_CLIENT_ID=from-dotenv\n")
    monkeypatch.chdir(repo)

    config = load_config(use_dotenv=False)

    assert config.client_id is None
    assert config.env_file is None
