"""A small, in-process, deterministic rate limiter (docs/PLAN.md §23.4/§23.5:
"account/IP-aware rate-limit abstractions for login/activation/reset/
pairing/token-exchange — portable, deterministic in tests, not over-
engineered").

Framework-free per docs/architecture/SYSTEM_ARCHITECTURE.md §5.4 — plain
stdlib only. `dnd_ai.api.local_auth`/`.foundry_pairing` own the actual
per-endpoint `RateLimiter` instances and the keys (e.g. `f"login:{ip}:
{login_name}"`) they check against.

Deliberately in-process, not backed by Redis/Memcached/a database table:
this codebase has no existing shared-cache infrastructure, and adding one
purely for rate limiting would be exactly the "not over-engineered"
over-reach the plan explicitly warns against. The real limitation this
carries — each Uvicorn worker process has its own independent counters, so
a multi-worker/horizontally-scaled deployment enforces the limit
*per worker*, not globally — is a known, documented scope boundary
(docs/PHASE11_VERIFICATION.md records it as such), not an oversight; the
current `compose.yaml` topology runs one `api` worker.

Deterministic in tests because `now` is always an explicit parameter, never
`datetime.now()` read internally — a test controls elapsed time exactly by
choosing what `now` to pass, with no real `sleep()` or wall-clock
dependency anywhere in this module.

Bounded key tracking (Phase 13B correction): a key here is frequently
caller-controlled text (a login name, a normalized account identifier) —
`defaultdict(list)`'s original shape recorded one dict entry per *distinct*
key forever, with no eviction, so an attacker who simply varies the key on
every request (a fresh login name each time) could grow this process's
memory without bound purely by making requests, never touching any
attempt-count ceiling. `RateLimiter` now caps the number of distinct keys
it tracks (`max_tracked_keys`) and evicts the least-recently-touched key
once that cap would be exceeded — an `OrderedDict` used as a simple LRU,
not a second timer/sweep thread. This bounds worst-case memory to
`O(max_tracked_keys * max_attempts)` regardless of how many distinct keys
are ever presented, while leaving every actually-active key's own count
exact and unaffected (eviction only ever removes the key touched least
recently, which is also the one likeliest to already be stale/expired).
"""

import threading
from collections import OrderedDict
from datetime import datetime, timedelta

# A generous default: large enough that no realistic single-endpoint test
# or production abuse-guard use in this codebase needs to override it, but
# small enough that the worst-case memory bound
# (max_tracked_keys * max_attempts datetimes) stays in the low megabytes
# even for a limiter configured with a large max_attempts.
_DEFAULT_MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    """A fixed-window counter per key, with a bounded number of distinct
    keys tracked (LRU-evicted). Not thread-hostile: a single
    `threading.Lock` guards the whole instance, which is fine at the
    request volumes a login/activation/reset/pairing endpoint sees (this
    is an abuse guard, not a hot path needing fine-grained concurrency)."""

    def __init__(
        self,
        *,
        max_attempts: int,
        window: timedelta,
        max_tracked_keys: int = _DEFAULT_MAX_TRACKED_KEYS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_tracked_keys < 1:
            raise ValueError("max_tracked_keys must be at least 1")
        self._max_attempts = max_attempts
        self._window = window
        self._max_tracked_keys = max_tracked_keys
        self._lock = threading.Lock()
        # Insertion/access order doubles as LRU order — every touch below
        # calls move_to_end(key), so the front of the dict is always the
        # least-recently-touched (and therefore first-evicted) key.
        self._attempts: OrderedDict[str, list[datetime]] = OrderedDict()

    def allow(self, key: str, *, now: datetime) -> bool:
        """Records and permits an attempt under `key` if fewer than
        `max_attempts` have occurred within `window` ending at `now`;
        otherwise denies it (and does not record the denied attempt, so a
        caller that keeps retrying while blocked does not further extend
        their own block past the original window). Touching `key` here
        (allowed or denied) always marks it most-recently-used, so an
        actively-retried key is never the one evicted to make room for a
        new one."""
        with self._lock:
            cutoff = now - self._window
            existing = self._attempts.get(key)
            fresh = [ts for ts in existing if ts > cutoff] if existing is not None else []
            if len(fresh) >= self._max_attempts:
                self._attempts[key] = fresh
                self._attempts.move_to_end(key)
                return False
            fresh.append(now)
            self._attempts[key] = fresh
            self._attempts.move_to_end(key)
            self._evict_least_recently_used_if_over_capacity()
            return True

    def _evict_least_recently_used_if_over_capacity(self) -> None:
        while len(self._attempts) > self._max_tracked_keys:
            self._attempts.popitem(last=False)

    def reset(self, key: str) -> None:
        """Clears `key`'s recorded attempts — called after a successful,
        sensitive operation (e.g. a successful login) so a legitimate
        user's next unrelated attempt is not penalized by earlier failed
        ones still sitting inside the window."""
        with self._lock:
            self._attempts.pop(key, None)

    def tracked_key_count(self) -> int:
        """The number of distinct keys currently tracked — exposed only so
        tests can assert the bound actually holds; not used by any
        production call site."""
        with self._lock:
            return len(self._attempts)
