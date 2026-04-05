"""
Tests for the sliding-window rate limiter.

Run: pytest tests/test_rate_limiter.py -v
"""

import time
import threading
from unittest.mock import patch

from app.services.rate_limiter import (
    check_rate_limit,
    clear,
    _buckets,
    _lock,
    _maybe_evict,
    _EVICTION_TTL,
    _MAX_BUCKETS,
)


def _clear_all():
    clear()


# -----------------------------------------------------------------------
# BASIC OPERATIONS
# -----------------------------------------------------------------------

def test_allows_under_limit():
    """Requests under the limit should be allowed."""
    _clear_all()
    limits = [(60, 5)]  # 5 per minute
    for _ in range(5):
        result = check_rate_limit("test-key", limits)
        assert result.allowed is True
    assert result.retry_after == 0


def test_blocks_over_limit():
    """The request that exceeds the limit should be blocked."""
    _clear_all()
    limits = [(60, 3)]  # 3 per minute
    for _ in range(3):
        result = check_rate_limit("test-key", limits)
        assert result.allowed is True

    result = check_rate_limit("test-key", limits)
    assert result.allowed is False
    assert result.retry_after >= 1
    assert result.limit == 3
    assert result.window == 60


def test_separate_keys_independent():
    """Different keys should have independent limits."""
    _clear_all()
    limits = [(60, 2)]
    check_rate_limit("key-a", limits)
    check_rate_limit("key-a", limits)
    result_a = check_rate_limit("key-a", limits)
    assert result_a.allowed is False

    # key-b should still be allowed
    result_b = check_rate_limit("key-b", limits)
    assert result_b.allowed is True


def test_multiple_windows():
    """Should enforce the tightest violated window."""
    _clear_all()
    limits = [
        (60, 3),     # 3 per minute
        (3600, 100),  # 100 per hour (not hit)
    ]
    for _ in range(3):
        check_rate_limit("test-key", limits)

    result = check_rate_limit("test-key", limits)
    assert result.allowed is False
    assert result.window == 60  # minute window was hit, not hour


def test_sliding_window_allows_after_expiry():
    """After the window passes, requests should be allowed again."""
    _clear_all()
    limits = [(1, 2)]  # 2 per 1 second

    check_rate_limit("test-key", limits)
    check_rate_limit("test-key", limits)
    result = check_rate_limit("test-key", limits)
    assert result.allowed is False

    # Wait for the window to expire
    time.sleep(1.1)
    result = check_rate_limit("test-key", limits)
    assert result.allowed is True


def test_retry_after_is_positive():
    """retry_after should always be at least 1 when blocked."""
    _clear_all()
    limits = [(60, 1)]
    check_rate_limit("test-key", limits)
    result = check_rate_limit("test-key", limits)
    assert result.allowed is False
    assert result.retry_after >= 1


def test_denied_requests_still_counted():
    """Denied requests should still be recorded so sustained abuse
    doesn't benefit from window drain."""
    _clear_all()
    limits = [(60, 2)]
    check_rate_limit("test-key", limits)
    check_rate_limit("test-key", limits)

    # These are denied but should still be recorded
    for _ in range(5):
        result = check_rate_limit("test-key", limits)
        assert result.allowed is False


def test_clear_specific_key():
    """clear(key) should only clear that key."""
    _clear_all()
    limits = [(60, 1)]
    check_rate_limit("key-a", limits)
    check_rate_limit("key-b", limits)

    clear("key-a")

    # key-a should be allowed again
    result_a = check_rate_limit("key-a", limits)
    assert result_a.allowed is True

    # key-b should still be blocked
    result_b = check_rate_limit("key-b", limits)
    assert result_b.allowed is False


def test_clear_all():
    """clear() with no args should clear all state."""
    _clear_all()
    limits = [(60, 1)]
    check_rate_limit("key-a", limits)
    check_rate_limit("key-b", limits)

    clear()

    assert check_rate_limit("key-a", limits).allowed is True
    assert check_rate_limit("key-b", limits).allowed is True


# -----------------------------------------------------------------------
# EVICTION
# -----------------------------------------------------------------------

def test_stale_entries_evicted():
    """Entries older than _EVICTION_TTL should be removed during eviction."""
    _clear_all()
    limits = [(60, 100)]
    check_rate_limit("stale-key", limits)

    with _lock:
        # Backdate the timestamp so the entry looks old
        bucket = _buckets["stale-key"]
        # Replace entries with timestamps from 2 hours ago
        bucket.clear()
        bucket.append(time.monotonic() - _EVICTION_TTL - 100)

        # Force eviction by backdating _last_eviction past the interval
        import app.services.rate_limiter as rl
        old_last = rl._last_eviction
        rl._last_eviction = time.monotonic() - rl._EVICTION_INTERVAL - 1
        _maybe_evict(time.monotonic())
        rl._last_eviction = old_last

    with _lock:
        assert "stale-key" not in _buckets


# -----------------------------------------------------------------------
# THREAD SAFETY
# -----------------------------------------------------------------------

def test_concurrent_rate_checks():
    """Concurrent rate checks should not raise or corrupt data."""
    _clear_all()
    limits = [(60, 1000)]  # high limit so we focus on thread safety
    errors = []
    num_threads = 10
    ops_per_thread = 50

    def worker(thread_id):
        try:
            for i in range(ops_per_thread):
                key = f"thread-{thread_id}"
                check_rate_limit(key, limits)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(errors) == 0, f"Thread safety errors: {errors}"


def test_concurrent_check_and_clear():
    """Concurrent checks and clears should not raise."""
    _clear_all()
    limits = [(60, 1000)]
    errors = []

    def checker():
        try:
            for _ in range(100):
                check_rate_limit("shared-key", limits)
        except Exception as e:
            errors.append(f"Checker: {e}")

    def clearer():
        try:
            for _ in range(100):
                clear("shared-key")
        except Exception as e:
            errors.append(f"Clearer: {e}")

    threads = [
        threading.Thread(target=checker),
        threading.Thread(target=checker),
        threading.Thread(target=clearer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(errors) == 0, f"Thread safety errors: {errors}"


# -----------------------------------------------------------------------
# D7 — FORCED EVICTION AT BUCKET CAP
# -----------------------------------------------------------------------

def test_forced_eviction_when_bucket_cap_exceeded():
    """When bucket count exceeds _MAX_BUCKETS, eviction should run
    immediately even if the interval hasn't elapsed."""
    import app.services.rate_limiter as rl

    _clear_all()

    # Populate with stale entries that are older than the TTL
    stale_time = time.monotonic() - _EVICTION_TTL - 100
    with _lock:
        for i in range(_MAX_BUCKETS + 100):
            from collections import deque
            bucket = deque(maxlen=1)
            bucket.append(stale_time)
            _buckets[f"stale-{i}"] = bucket

        # Set last_eviction to now so the interval check would skip eviction
        rl._last_eviction = time.monotonic()

        # Bucket count exceeds cap, so eviction should be forced
        assert len(_buckets) > _MAX_BUCKETS
        _maybe_evict(time.monotonic())

        # All stale entries should have been cleaned up
        assert len(_buckets) == 0

    _clear_all()


def test_no_forced_eviction_under_cap():
    """When bucket count is under _MAX_BUCKETS, eviction should respect
    the interval timer."""
    import app.services.rate_limiter as rl

    _clear_all()

    # Add a small number of stale entries (under cap)
    stale_time = time.monotonic() - _EVICTION_TTL - 100
    with _lock:
        for i in range(10):
            from collections import deque
            bucket = deque(maxlen=1)
            bucket.append(stale_time)
            _buckets[f"stale-{i}"] = bucket

        # Set last_eviction to now — interval check should skip eviction
        rl._last_eviction = time.monotonic()

        assert len(_buckets) == 10
        _maybe_evict(time.monotonic())

        # Entries should still be there since interval hasn't elapsed
        # and we're under the cap
        assert len(_buckets) == 10

    _clear_all()
