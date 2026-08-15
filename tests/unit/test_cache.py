"""Cache freshness and stale-fallback policy.

Time is injected, never slept on, so every assertion about age and staleness
is exact and platform-independent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.cache import CachedValue, TTLCache
from yahoo_fantasy_mcp.errors import (
    YahooNotProvisionedError,
    YahooServiceError,
    YahooTransportError,
)


class FakeClock:
    """Deterministic clock. `advance()` is the only way time moves."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _boom(exc):
    def fetch():
        raise exc

    return fetch


# -- basic caching ---------------------------------------------------------


def test_cache_hit_avoids_refetch():
    calls = []

    def fetch():
        calls.append(1)
        return {"n": len(calls)}

    cache = TTLCache(ttl_seconds=100, clock=FakeClock())
    first = cache.get_or_fetch("k", fetch)
    second = cache.get_or_fetch("k", fetch)

    assert len(calls) == 1
    assert first["data"] == second["data"]
    assert second["stale"] is False


def test_force_refresh_bypasses_cache():
    calls = []

    def fetch():
        calls.append(1)
        return len(calls)

    cache = TTLCache(ttl_seconds=1000, clock=FakeClock())
    cache.get_or_fetch("k", fetch)
    cache.get_or_fetch("k", fetch, force_refresh=True)
    assert len(calls) == 2


def test_invalidate_clears_one_or_all_keys():
    cache = TTLCache(ttl_seconds=1000, clock=FakeClock())
    cache.get_or_fetch("a", lambda: 1)
    cache.get_or_fetch("b", lambda: 2)
    cache.invalidate("a")
    assert "a" not in cache._store
    assert "b" in cache._store
    cache.invalidate()
    assert cache._store == {}


def test_envelope_marks_an_over_age_value_stale():
    value = CachedValue(value=1, fetched_at=1000.0)
    envelope = value.as_envelope(ttl_seconds=10, now=1100.0)
    assert envelope["age_seconds"] == 100.0
    assert envelope["stale"] is True


# -- the stale-fallback policy, case by case -------------------------------


def test_fresh_hit_returns_cached_data_not_stale():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    clock.advance(30)  # still inside the TTL
    envelope = cache.get_or_fetch("k", _boom(YahooTransportError("must not be called")))

    assert envelope["data"] == "first"
    assert envelope["stale"] is False
    assert envelope["age_seconds"] == 30.0
    assert envelope["refresh_failed"] is False
    assert envelope["refresh_error"] is None


def test_expired_plus_successful_refresh_returns_new_data_not_stale():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    clock.advance(120)  # past the TTL
    envelope = cache.get_or_fetch("k", lambda: "second")

    assert envelope["data"] == "second"
    assert envelope["stale"] is False
    assert envelope["age_seconds"] == 0.0
    assert envelope["refresh_failed"] is False


@pytest.mark.parametrize(
    "failure",
    [
        YahooTransportError("Yahoo API unreachable: ConnectTimeout"),
        YahooServiceError("Yahoo API error 503"),
    ],
)
def test_expired_plus_expected_failure_serves_labeled_stale_data(failure):
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    clock.advance(300)
    envelope = cache.get_or_fetch("k", _boom(failure))

    assert envelope["data"] == "first"
    assert envelope["stale"] is True
    assert envelope["age_seconds"] == 300.0  # the real age, not a reset one
    assert envelope["refresh_failed"] is True

    error = envelope["refresh_error"]
    assert error["error_type"] == failure.error_type
    assert error["retryable"] is True
    assert error["data"] is None
    assert "error" in error


def test_no_cached_value_plus_failure_raises_the_real_error():
    cache = TTLCache(ttl_seconds=60, clock=FakeClock())

    with pytest.raises(YahooTransportError):
        cache.get_or_fetch("k", _boom(YahooTransportError("down")))


def test_force_refresh_plus_failure_never_falls_back_silently():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")
    clock.advance(300)

    with pytest.raises(YahooTransportError):
        cache.get_or_fetch("k", _boom(YahooTransportError("down")), force_refresh=True)


def test_force_refresh_failure_leaves_the_previous_value_intact():
    """Failing a forced refresh must not destroy what we already had."""

    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    with pytest.raises(YahooTransportError):
        cache.get_or_fetch("k", _boom(YahooTransportError("down")), force_refresh=True)

    envelope = cache.get_or_fetch("k", lambda: "unused")
    assert envelope["data"] == "first"


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("parser broke on an unexpected Yahoo shape"),
        KeyError("fantasy_content"),
        TypeError("programming error"),
        YahooNotProvisionedError("Yahoo has not provisioned this app"),
    ],
)
def test_parser_and_non_transport_errors_are_never_hidden_as_stale_data(failure):
    """A bug or a hard auth/provisioning state must surface, not be papered over."""

    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")
    clock.advance(300)

    with pytest.raises(type(failure)):
        cache.get_or_fetch("k", _boom(failure))


def test_successful_refresh_after_a_stale_fallback_clears_the_flags():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    clock.advance(300)
    stale = cache.get_or_fetch("k", _boom(YahooTransportError("down")))
    assert stale["stale"] is True

    clock.advance(1)
    recovered = cache.get_or_fetch("k", lambda: "second")
    assert recovered["data"] == "second"
    assert recovered["stale"] is False
    assert recovered["refresh_failed"] is False
    assert recovered["refresh_error"] is None


def test_stale_fallback_does_not_overwrite_the_cached_timestamp():
    """Repeated failures keep reporting a growing real age."""

    clock = FakeClock()
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_fetch("k", lambda: "first")

    clock.advance(200)
    first_failure = cache.get_or_fetch("k", _boom(YahooTransportError("down")))
    clock.advance(100)
    second_failure = cache.get_or_fetch("k", _boom(YahooTransportError("down")))

    assert first_failure["age_seconds"] == 200.0
    assert second_failure["age_seconds"] == 300.0
