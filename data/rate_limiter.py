"""Thread-safe token-bucket rate limiter for the AlgoDesk data layer.

Provides a generic token-bucket implementation suitable for throttling
API calls to broker endpoints (e.g. Upstox: 50 req/s + 500 req/min).

Classes:
    TokenBucketRateLimiter  – single-bucket, thread-safe limiter.
    CompositeRateLimiter    – wraps multiple buckets; all must be satisfied.

Factory:
    create_rate_limiter     – convenience constructor for common patterns.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Sequence

logger = logging.getLogger(__name__)

_RETRY_SLEEP_S: float = 0.01  # 10 ms – avoids spin-locking in acquire()


class TokenBucketRateLimiter:
    """A thread-safe token-bucket rate limiter.

    Tokens are added at *refill_rate* tokens/second up to *capacity*.
    Each :meth:`acquire` / :meth:`try_acquire` consumes exactly one token.
    """

    __slots__ = ("_capacity", "_refill_rate", "_tokens", "_last_refill", "_lock")

    def __init__(self, capacity: float, refill_rate: float) -> None:
        """Initialise the bucket.

        Args:
            capacity: Maximum number of tokens the bucket can hold.
            refill_rate: Tokens added per second.

        Raises:
            ValueError: If *capacity* or *refill_rate* is not positive.
        """
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if refill_rate <= 0:
            raise ValueError(f"refill_rate must be positive, got {refill_rate}")

        self._capacity: float = capacity
        self._refill_rate: float = refill_rate
        self._tokens: float = capacity
        self._last_refill: float = time.monotonic()
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """Add tokens accrued since the last refill (caller holds lock)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Release lock before sleeping to let other threads proceed.
            time.sleep(_RETRY_SLEEP_S)

    def try_acquire(self) -> bool:
        """Try to consume a token without blocking.

        Returns:
            ``True`` if a token was consumed, ``False`` otherwise.
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        with self._lock:
            self._tokens = self._capacity
            self._last_refill = time.monotonic()

    def __repr__(self) -> str:
        return (
            f"TokenBucketRateLimiter(capacity={self._capacity}, "
            f"refill_rate={self._refill_rate})"
        )


class CompositeRateLimiter:
    """Wraps multiple :class:`TokenBucketRateLimiter` instances.

    :meth:`acquire` succeeds only after *every* underlying bucket has
    granted a token — useful for APIs with layered rate limits
    (e.g. 50 req/s **and** 500 req/min).
    """

    __slots__ = ("_limiters",)

    def __init__(self, limiters: Sequence[TokenBucketRateLimiter]) -> None:
        if not limiters:
            raise ValueError("At least one limiter is required")
        self._limiters: tuple[TokenBucketRateLimiter, ...] = tuple(limiters)

    def acquire(self) -> None:
        """Block until a token is available in **all** buckets."""
        for limiter in self._limiters:
            limiter.acquire()

    def try_acquire(self) -> bool:
        """Non-blocking acquire across all buckets.

        Tokens are consumed only if **every** bucket can provide one.
        If any bucket refuses, tokens already consumed in this call are
        *not* rolled back (best-effort; use :meth:`acquire` for strict
        guarantees).
        """
        return all(limiter.try_acquire() for limiter in self._limiters)

    def reset(self) -> None:
        """Reset every underlying bucket to full capacity."""
        for limiter in self._limiters:
            limiter.reset()

    def __repr__(self) -> str:
        return f"CompositeRateLimiter(limiters={self._limiters!r})"


def create_rate_limiter(
    requests_per_second: float,
    requests_per_minute: float | None = None,
) -> TokenBucketRateLimiter | CompositeRateLimiter:
    """Factory for common rate-limiting patterns.

    Args:
        requests_per_second: Maximum sustained requests per second.
        requests_per_minute: Optional per-minute cap.  When provided a
            :class:`CompositeRateLimiter` with two buckets is returned.

    Returns:
        A single :class:`TokenBucketRateLimiter` when only *requests_per_second*
        is given, otherwise a :class:`CompositeRateLimiter`.
    """
    per_second = TokenBucketRateLimiter(
        capacity=requests_per_second,
        refill_rate=requests_per_second,
    )
    if requests_per_minute is None:
        logger.debug("Created rate limiter: %s req/s", requests_per_second)
        return per_second

    per_minute = TokenBucketRateLimiter(
        capacity=requests_per_minute,
        refill_rate=requests_per_minute / 60.0,
    )
    logger.debug(
        "Created composite rate limiter: %s req/s, %s req/min",
        requests_per_second,
        requests_per_minute,
    )
    return CompositeRateLimiter([per_second, per_minute])
