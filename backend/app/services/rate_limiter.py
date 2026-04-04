"""
In-memory sliding-window rate limiter.

Two-tier design:
  - Per-session limits (primary) — generous per-conversation caps.
  - Per-IP limits (secondary, much higher) — safety net against brute-force
    abuse that creates many sessions.  Set high so shared WiFi at shelters
    and libraries never triggers a block.

All state lives in-process and resets on restart — acceptable for
single-process deployments on Render free tier.
"""

import os
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration — overridable via env vars for production tuning
# ---------------------------------------------------------------------------

SESSION_PER_MINUTE = int(os.getenv("RATE_LIMIT_SESSION_PER_MIN", "12"))
SESSION_PER_HOUR = int(os.getenv("RATE_LIMIT_SESSION_PER_HOUR", "60"))
SESSION_PER_DAY = int(os.getenv("RATE_LIMIT_SESSION_PER_DAY", "200"))

IP_PER_MINUTE = int(os.getenv("RATE_LIMIT_IP_PER_MIN", "60"))
IP_PER_HOUR = int(os.getenv("RATE_LIMIT_IP_PER_HOUR", "300"))

FEEDBACK_PER_MINUTE = int(os.getenv("RATE_LIMIT_FEEDBACK_PER_MIN", "10"))

# How long to keep entries with no new requests before evicting (seconds).
_EVICTION_TTL = 3600  # 1 hour

# Minimum interval between eviction sweeps (seconds).
_EVICTION_INTERVAL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Limit definitions — each is a (window_seconds, max_requests) pair
# ---------------------------------------------------------------------------

CHAT_SESSION_LIMITS: List[Tuple[int, int]] = [
    (60, SESSION_PER_MINUTE),
    (3600, SESSION_PER_HOUR),
    (86400, SESSION_PER_DAY),
]

CHAT_IP_LIMITS: List[Tuple[int, int]] = [
    (60, IP_PER_MINUTE),
    (3600, IP_PER_HOUR),
]

FEEDBACK_SESSION_LIMITS: List[Tuple[int, int]] = [
    (60, FEEDBACK_PER_MINUTE),
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int  # seconds until the tightest violated window resets (0 if allowed)
    limit: int        # the max_requests value that was hit (0 if allowed)
    window: int       # the window_seconds value that was hit (0 if allowed)


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

# key -> deque of monotonic timestamps
_buckets: Dict[str, deque] = {}
_lock = threading.Lock()
_last_eviction: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_rate_limit(
    key: str,
    limits: List[Tuple[int, int]],
) -> RateLimitResult:
    """Record a request for *key* and check it against *limits*.

    Each limit is a ``(window_seconds, max_requests)`` pair.  If any window
    is exceeded, the request is denied.  The tightest (shortest retry_after)
    violated window drives the ``retry_after`` value.

    The request timestamp is always recorded — even if denied — so that
    sustained flooding doesn't cause the window to "drain" while the
    attacker waits.
    """
    now = time.monotonic()

    with _lock:
        _maybe_evict(now)

        bucket = _buckets.get(key)
        if bucket is None:
            # Max capacity = largest max_requests across all limits
            maxlen = max(m for _, m in limits) if limits else 1
            bucket = deque(maxlen=maxlen)
            _buckets[key] = bucket

        # Check all windows BEFORE recording the new request
        tightest: Optional[RateLimitResult] = None
        for window_seconds, max_requests in limits:
            count = _count_in_window(bucket, window_seconds, now)
            if count >= max_requests:
                retry_after = _retry_after(bucket, window_seconds, now)
                if tightest is None or retry_after < tightest.retry_after:
                    tightest = RateLimitResult(
                        allowed=False,
                        retry_after=retry_after,
                        limit=max_requests,
                        window=window_seconds,
                    )

        if tightest is not None:
            # Still record the timestamp so sustained abuse doesn't
            # benefit from a draining window.
            bucket.append(now)
            return tightest

        # Allowed — record and return
        bucket.append(now)
        return RateLimitResult(allowed=True, retry_after=0, limit=0, window=0)


def clear(key: Optional[str] = None) -> None:
    """Clear rate limit state.  Pass a key to clear one entry, or None for all.

    Intended for testing.
    """
    with _lock:
        if key is None:
            _buckets.clear()
        else:
            _buckets.pop(key, None)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _count_in_window(bucket: deque, window_seconds: int, now: float) -> int:
    """Count timestamps within the last *window_seconds*."""
    cutoff = now - window_seconds
    # deque is in chronological order — scan from the left
    count = 0
    for ts in reversed(bucket):
        if ts > cutoff:
            count += 1
        else:
            break
    return count


def _retry_after(bucket: deque, window_seconds: int, now: float) -> int:
    """Seconds until the oldest request in the window expires."""
    cutoff = now - window_seconds
    for ts in bucket:
        if ts > cutoff:
            return max(1, int(ts - cutoff) + 1)
    return 1  # fallback


def _maybe_evict(now: float) -> None:
    """Remove buckets with no recent activity.  MUST hold _lock."""
    global _last_eviction
    if now - _last_eviction < _EVICTION_INTERVAL:
        return
    _last_eviction = now
    cutoff = now - _EVICTION_TTL
    stale = [k for k, bucket in _buckets.items() if not bucket or bucket[-1] < cutoff]
    for k in stale:
        del _buckets[k]
