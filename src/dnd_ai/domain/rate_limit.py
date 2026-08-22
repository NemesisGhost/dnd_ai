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
"""

import threading
from collections import defaultdict
from datetime import datetime, timedelta


class RateLimiter:
    """A fixed-window counter per key. Not thread-hostile: a single
    `threading.Lock` guards the whole instance, which is fine at the
    request volumes a login/activation/reset/pairing endpoint sees (this
    is an abuse guard, not a hot path needing fine-grained concurrency)."""

    def __init__(self, *, max_attempts: int, window: timedelta) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._max_attempts = max_attempts
        self._window = window
        self._lock = threading.Lock()
        self._attempts: dict[str, list[datetime]] = defaultdict(list)

    def allow(self, key: str, *, now: datetime) -> bool:
        """Records and permits an attempt under `key` if fewer than
        `max_attempts` have occurred within `window` ending at `now`;
        otherwise denies it (and does not record the denied attempt, so a
        caller that keeps retrying while blocked does not further extend
        their own block past the original window)."""
        with self._lock:
            cutoff = now - self._window
            fresh = [ts for ts in self._attempts[key] if ts > cutoff]
            if len(fresh) >= self._max_attempts:
                self._attempts[key] = fresh
                return False
            fresh.append(now)
            self._attempts[key] = fresh
            return True

    def reset(self, key: str) -> None:
        """Clears `key`'s recorded attempts — called after a successful,
        sensitive operation (e.g. a successful login) so a legitimate
        user's next unrelated attempt is not penalized by earlier failed
        ones still sitting inside the window."""
        with self._lock:
            self._attempts.pop(key, None)
