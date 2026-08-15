import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yahoo_fantasy_mcp.cache import CachedValue, TTLCache


def test_envelope_marks_an_over_age_value_stale():
    # The envelope is what labels age/staleness. Note that TTLCache.get_or_fetch
    # always re-fetches an expired key -- there is no stale-fallback path that
    # serves an over-age value -- so this exercises the labeling directly.
    value = CachedValue(value=1, fetched_at=1000.0)
    envelope = value.as_envelope(ttl_seconds=10, now=1100.0)
    assert envelope["age_seconds"] == 100.0
    assert envelope["stale"] is True


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
    cache = TTLCache(ttl_seconds=10)
    envelope = cache.get_or_fetch("k", lambda: 42)
    assert envelope["data"] == 42
    assert "fetched_at" in envelope
    assert envelope["ttl_seconds"] == 10
    assert envelope["age_seconds"] >= 0
    assert envelope["stale"] is False

    # Age the entry past the TTL deterministically rather than sleeping --
    # wall-clock resolution is too coarse on some platforms to make a
    # ttl_seconds=0 entry reliably expire within the same tick.
    cache._store["k"].fetched_at -= 60
    refreshed = cache.get_or_fetch("k", lambda: 99, force_refresh=False)
    assert refreshed["data"] == 99  # expired entry is re-fetched, not served stale
    assert refreshed["stale"] is False


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
