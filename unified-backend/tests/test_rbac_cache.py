# test_rbac_cache.py
#
# Pure unit tests for the in-memory, version-keyed TTL cache backing
# app.dependencies.auth.get_current_user's cache-hit fast path. No DB,
# no event loop dependency — see test_get_current_user_cache.py for
# the end-to-end behavior against a real user row.

import time

from app.core.rbac_cache import RBACCache


def test_unknown_key_is_a_miss():
    cache = RBACCache(ttl_seconds=30, max_size=10)
    assert cache.is_valid("user-1", 1) is False


def test_marked_key_is_valid_until_expiry():
    cache = RBACCache(ttl_seconds=30, max_size=10)
    cache.mark_valid("user-1", 1)
    assert cache.is_valid("user-1", 1) is True


def test_different_permission_version_is_a_miss():
    """
    The whole point of keying on (user_id, permission_version): a
    stale token's version doesn't accidentally hit a cache entry
    populated under a newer (or older) version for the same user.
    """

    cache = RBACCache(ttl_seconds=30, max_size=10)
    cache.mark_valid("user-1", 1)
    assert cache.is_valid("user-1", 2) is False
    assert cache.is_valid("user-1", 1) is True


def test_entry_expires_after_ttl():
    cache = RBACCache(ttl_seconds=0.05, max_size=10)
    cache.mark_valid("user-1", 1)
    assert cache.is_valid("user-1", 1) is True
    time.sleep(0.1)
    assert cache.is_valid("user-1", 1) is False


def test_invalidate_removes_without_scanning_others():
    cache = RBACCache(ttl_seconds=30, max_size=10)
    cache.mark_valid("user-1", 1)
    cache.mark_valid("user-2", 1)
    cache.invalidate("user-1", 1)
    assert cache.is_valid("user-1", 1) is False
    assert cache.is_valid("user-2", 1) is True


def test_lru_eviction_when_max_size_exceeded():
    cache = RBACCache(ttl_seconds=30, max_size=2)
    cache.mark_valid("user-1", 1)
    cache.mark_valid("user-2", 1)
    cache.mark_valid("user-3", 1)  # should evict user-1 (least recently used)

    assert len(cache) == 2
    assert cache.is_valid("user-1", 1) is False
    assert cache.is_valid("user-2", 1) is True
    assert cache.is_valid("user-3", 1) is True


def test_reading_an_entry_protects_it_from_lru_eviction():
    cache = RBACCache(ttl_seconds=30, max_size=2)
    cache.mark_valid("user-1", 1)
    cache.mark_valid("user-2", 1)
    cache.is_valid("user-1", 1)  # touch user-1, making user-2 the LRU one
    cache.mark_valid("user-3", 1)  # should evict user-2, not user-1

    assert cache.is_valid("user-1", 1) is True
    assert cache.is_valid("user-2", 1) is False
    assert cache.is_valid("user-3", 1) is True
