"""TTL cache that surfaces staleness instead of hiding it.

Every cached read comes back wrapped with `fetched_at`, `age_seconds`, and
`stale`. Callers (and the assistant reading tool output) can see exactly how
old a number is rather than trusting a silently-served cache hit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar


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
        }


@dataclass(slots=True)
class TTLCache:
    """A tiny in-memory cache. One process, one server instance.

    Not distributed and not persisted across restarts on purpose -- a
    lineup decision tool should not survive a restart holding a silently
    aged number.
    """

    ttl_seconds: int = 120
    _store: dict[str, CachedValue[Any]] = field(default_factory=dict)

    def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], Any],
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        now = time.time()
        cached = self._store.get(key)
        if force_refresh or cached is None or (now - cached.fetched_at) > self.ttl_seconds:
            value = fetch()
            cached = CachedValue(value=value, fetched_at=now)
            self._store[key] = cached
        return cached.as_envelope(self.ttl_seconds, now=now)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)
