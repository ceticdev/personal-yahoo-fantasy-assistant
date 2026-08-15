import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yahoo_fantasy_mcp.cache import TTLCache


def test_cache_hit_avoids_refetch():
    calls = []

    def fetch():
        calls.append(1)
        return {"n": len(calls)}

    cache = TTLCache(ttl_seconds=100)
    first = cache.get_or_fetch("k", fetch)
    second = cache.get_or_fetch("k", fetch)

    assert len(calls) == 1
    assert first["data"] == second["data"]
    assert second["stale"] is False


def test_cache_envelope_reports_age_and_staleness():
    cache = TTLCache(ttl_seconds=0)
    envelope = cache.get_or_fetch("k", lambda: 42)
    assert envelope["data"] == 42
    assert "fetched_at" in envelope
    assert envelope["ttl_seconds"] == 0
    # age_seconds is >= 0 immediately; with ttl=0 it's stale on the very next check
    stale_check = cache.get_or_fetch("k", lambda: 99, force_refresh=False)
    assert stale_check["data"] == 99  # ttl=0 means every read re-fetches


def test_force_refresh_bypasses_cache():
    calls = []

    def fetch():
        calls.append(1)
        return len(calls)

    cache = TTLCache(ttl_seconds=1000)
    cache.get_or_fetch("k", fetch)
    cache.get_or_fetch("k", fetch, force_refresh=True)
    assert len(calls) == 2


def test_invalidate_clears_one_or_all_keys():
    cache = TTLCache(ttl_seconds=1000)
    cache.get_or_fetch("a", lambda: 1)
    cache.get_or_fetch("b", lambda: 2)
    cache.invalidate("a")
    assert "a" not in cache._store
    assert "b" in cache._store
    cache.invalidate()
    assert cache._store == {}
