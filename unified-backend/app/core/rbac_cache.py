# rbac_cache.py
"""
A small in-memory, TTL-based, version-keyed cache that lets
app.dependencies.auth.get_current_user skip its Postgres round trip on
the common case, without weakening the security property that used to
justify that round trip (catching a deactivated/reassigned account
before its JWT naturally expires).

How this replaces a per-request DB check:

- Every access token carries a `permission_version` claim, a snapshot
  of shared_models.models.User.permission_version at the moment the
  token was issued (see AuthService.login/refresh_token).
- That column is bumped (see app/rbac/services/user_service.py,
  permission_override_service.py, role_permission_service.py) whenever
  anything auth-relevant about the user changes: role, category,
  manager/teamlead, active/inactive, a personal permission override,
  or (bulk, one UPDATE) their role's own permission set.
- A cache entry for (user_id, permission_version) means "as of some
  point in the last `ttl_seconds`, Postgres confirmed this user was
  active and this was in fact their current permission_version." On a
  cache hit, get_current_user trusts the JWT's own role/category
  claims (they must still be accurate, or the version would differ)
  and never touches the DB. On a miss (first request, TTL expired, or
  a token whose version doesn't match anything cached), it does the
  existing DB lookup, and if the DB's live permission_version doesn't
  match the token's claim, the caller is expected to reject the
  request outright — the token is for a superseded version of this
  user's authorization state.

Deliberately NOT a general-purpose cache: bumping a version never
touches this cache directly (see the module-level docstring in
shared_models' User.permission_version column) — a bump just means the
*next* miss-driven DB check will disagree with an already-cached
older version, and that stale entry is left to expire on its own TTL
rather than being scanned for and evicted. This is what makes
invalidation O(1) regardless of how many entries are cached.

Per-process only — the intended and accepted tradeoff for avoiding
Redis (see this module's home in the "eliminate the per-request RBAC
round trip" plan). Each worker process/instance has its own cache and
independently re-verifies against Postgres at least once per TTL
window per user; there is no cross-process invalidation signal.
"""

import asyncio
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)


class RBACCache:
    """
    Thread-safe TTL cache keyed on (user_id, permission_version).
    Values are meaningless — presence (and non-expiry) of the key is
    the entire signal ("this pair was confirmed valid recently").
    LRU eviction once `max_size` is exceeded.
    """

    def __init__(self, ttl_seconds: float, max_size: int):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_size <= 0:
            raise ValueError("max_size must be positive")

        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._lock = threading.Lock()
        # key -> expires_at (time.monotonic() timestamp)
        self._entries: "OrderedDict[tuple[str, int], float]" = OrderedDict()

    def is_valid(self, user_id: str, permission_version: int) -> bool:
        """
        True if (user_id, permission_version) was marked valid within
        the last `ttl_seconds`. Expired entries are dropped lazily,
        here, on read — no background thread/timer needed.
        """

        key = (user_id, permission_version)
        now = time.monotonic()

        with self._lock:
            expires_at = self._entries.get(key)
            if expires_at is None:
                return False
            if expires_at <= now:
                del self._entries[key]
                return False
            # Touch for LRU purposes — a still-active session's entry
            # should be the last evicted under memory pressure.
            self._entries.move_to_end(key)
            return True

    def mark_valid(self, user_id: str, permission_version: int) -> None:
        """Record that (user_id, permission_version) was just confirmed against Postgres."""

        key = (user_id, permission_version)
        expires_at = time.monotonic() + self._ttl_seconds

        with self._lock:
            self._entries[key] = expires_at
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)
        logger.info("RBAC_CACHE_SET")

    def invalidate(self, user_id: str, permission_version: int) -> None:
        """
        Not used by the normal request path (bumping permission_version
        in the DB is sufficient — see the module docstring). Exposed
        for tests and for an explicit "force this exact session to
        re-check now" escape hatch, without needing to scan the cache.
        """

        with self._lock:
            self._entries.pop((user_id, permission_version), None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_cache: RBACCache | None = None


def get_rbac_cache() -> RBACCache:
    """
    Module-level singleton, lazily built from Settings so tests can
    override rbac_cache_ttl_seconds/rbac_cache_max_size via env vars
    before first use. One instance per process, matching the
    per-process-cache design (see module docstring).
    """

    global _cache
    if _cache is None:
        from app.core.config import get_settings

        settings = get_settings()
        _cache = RBACCache(
            ttl_seconds=settings.rbac_cache_ttl_seconds,
            max_size=settings.rbac_cache_max_size,
        )
    return _cache


# --------------------------------------------------------------------
# Single-flight coalescing for cache-miss resolution
#
# is_valid()/mark_valid() above only cover the read/write of an already-
# resolved result; they say nothing about what happens when N concurrent
# requests all miss the cache for the *same* user at once (a burst of
# duplicate requests, e.g. a frontend bug, or simply many tabs/components
# querying at once right after login or a TTL expiry). Without
# coordination, all N independently fall through to their own Postgres
# round trip in app.dependencies.auth.get_current_user — the cache
# doesn't protect against this "stampede on miss" case at all, since
# nothing marks a key as valid until after a lookup has already
# completed.
#
# resolution_lock(user_id) serializes concurrent misses per user_id: the
# first caller through actually resolves (queries Postgres, calls
# mark_valid()); every other concurrent caller for the same user_id
# blocks until the first is done, then finds the cache already warm and
# takes the normal cache-hit path instead of also querying Postgres.
# Locks are created/removed on demand — cheap (a plain dict + asyncio
# .Lock, no persistence) and bounded to "users with a resolution
# currently in flight", not "every user ever seen".
# --------------------------------------------------------------------

_resolution_locks: dict[str, asyncio.Lock] = {}
_resolution_waiters: dict[str, int] = {}


@asynccontextmanager
async def resolution_lock(user_id: str):
    """
    Async context manager: serializes cache-miss resolution for one
    user_id. Callers should re-check `cache.is_valid(...)` immediately
    after entering — the whole point is that a concurrent caller may
    have already resolved and populated the cache while this one was
    waiting for the lock, letting it skip its own DB round trip.

    Safe to create/enter concurrently for different user_ids (each gets
    its own independent lock) — this only serializes requests that
    would otherwise redundantly resolve the exact same user at the
    exact same moment.
    """

    # Safe without an extra guard lock: dict.get/__setitem__ are plain
    # synchronous operations with no `await` between them, so nothing
    # else can interleave on this single-threaded event loop.
    lock = _resolution_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _resolution_locks[user_id] = lock
    _resolution_waiters[user_id] = _resolution_waiters.get(user_id, 0) + 1

    try:
        async with lock:
            yield
    finally:
        _resolution_waiters[user_id] -= 1
        if _resolution_waiters[user_id] <= 0:
            _resolution_locks.pop(user_id, None)
            _resolution_waiters.pop(user_id, None)
