"""TTL cache that surfaces staleness instead of hiding it -- and, when a
refresh genuinely fails upstream, serves the previous value clearly labeled
rather than turning a momentary Yahoo outage into a hard error.

The policy, exactly:

============================================  ==========================================
Situation                                     Result
============================================  ==========================================
Fresh cache hit                               cached data, ``stale=False``
Expired + refresh succeeds                    new data, ``stale=False``
Expired + refresh fails (transport/service)   old data, ``stale=True``, real
                                              ``age_seconds``, ``refresh_failed=True``,
                                              structured ``refresh_error``
No cached value + refresh fails               the failure propagates
``force_refresh=True`` + refresh fails        the failure propagates (never a silent
                                              fallback to old data)
Parser/validation/programming error           the failure propagates, always
============================================  ==========================================

Only exception types listed in `errors.STALE_FALLBACK_ELIGIBLE` are eligible
for the fallback. A parser bug or a bad argument must never be laundered into
"here is some old data" -- that would hide a real defect behind a plausible
looking answer.

`clock` is injectable so tests can control time exactly rather than sleeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from .errors import STALE_FALLBACK_ELIGIBLE, error_envelope

T = TypeVar("T")


@dataclass(slots=True)
class CachedValue(Generic[T]):
    value: T
    fetched_at: float

    def as_envelope(self, ttl_seconds: int, now: float | None = None) -> dict[str, Any]:
        current = now if now is not None else time.time()
        age = max(0.0, current - self.fetched_at)
        return {
            "data": self.value,
            "fetched_at": self.fetched_at,
            "age_seconds": round(age, 1),
            "stale": age > ttl_seconds,
            "ttl_seconds": ttl_seconds,
            "refresh_failed": False,
            "refresh_error": None,
        }


@dataclass(slots=True)
class TTLCache:
    """A tiny in-memory cache. One process, one server instance.

    Not distributed and not persisted across restarts on purpose -- a
    lineup decision tool should not survive a restart holding a silently
    aged number.
    """

    ttl_seconds: int = 120
    clock: Callable[[], float] = time.time
    _store: dict[str, CachedValue[Any]] = field(default_factory=dict)

    def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], Any],
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        now = self.clock()
        cached = self._store.get(key)
        is_expired = cached is None or (now - cached.fetched_at) > self.ttl_seconds

        if not force_refresh and cached is not None and not is_expired:
            return cached.as_envelope(self.ttl_seconds, now=now)

        try:
            value = fetch()
        except STALE_FALLBACK_ELIGIBLE as exc:
            # An expected upstream failure. If we hold a previous value and the
            # caller did not demand a forced refresh, hand back the old value
            # clearly labeled. Otherwise the caller gets the real error.
            if cached is None or force_refresh:
                raise
            envelope = cached.as_envelope(self.ttl_seconds, now=now)
            envelope["stale"] = True
            envelope["refresh_failed"] = True
            envelope["refresh_error"] = error_envelope(exc)
            return envelope

        fresh = CachedValue(value=value, fetched_at=now)
        self._store[key] = fresh
        return fresh.as_envelope(self.ttl_seconds, now=now)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)
