"""Token-bucket rate limiter with per-tenant buckets. Thread-safe, clock is injectable."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucket:
    """Classic token bucket. `capacity` is the burst size, `refill_rate` is tokens per second."""

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or refill_rate < 0:
            raise ValueError("capacity must be > 0 and refill_rate >= 0")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)

    def try_acquire(self, amount: float = 1.0) -> bool:
        """Take `amount` tokens if available. Requests larger than capacity never succeed."""
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with self._lock:
            self._refill()
            if amount > self._tokens:
                return False
            self._tokens -= amount
            return True

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class TenantLimiter:
    """One bucket per tenant, created lazily. Unknown tenants get the default limits."""

    def __init__(
        self,
        default_capacity: float,
        default_refill_rate: float,
        overrides: dict[str, tuple[float, float]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._default = (default_capacity, default_refill_rate)
        self._overrides = overrides or {}
        self._clock = clock
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def _bucket(self, tenant: str) -> TokenBucket:
        with self._lock:
            b = self._buckets.get(tenant)
            if b is None:
                cap, rate = self._overrides.get(tenant, self._default)
                b = TokenBucket(cap, rate, self._clock)
                self._buckets[tenant] = b
            return b

    def allow(self, tenant: str, cost: float = 1.0) -> bool:
        return self._bucket(tenant).try_acquire(cost)
