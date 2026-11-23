import threading

from aidelivery.quota import TenantLimiter, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_burst_then_reject() -> None:
    b = TokenBucket(3, 1, FakeClock())
    assert [b.try_acquire() for _ in range(4)] == [True, True, True, False]


def test_refill_over_time_and_cap() -> None:
    c = FakeClock()
    b = TokenBucket(5, 2, c)
    assert b.try_acquire(5)
    c.t = 1.0
    assert b.tokens == 2.0
    c.t = 100.0
    assert b.tokens == 5.0  # never exceeds capacity


def test_request_larger_than_capacity_never_succeeds() -> None:
    b = TokenBucket(5, 100, FakeClock())
    assert not b.try_acquire(6)
    assert b.tokens == 5.0  # a failed acquire consumes nothing


def test_clock_going_backwards_does_not_add_tokens() -> None:
    c = FakeClock()
    c.t = 10.0
    b = TokenBucket(2, 1, c)
    assert b.try_acquire(2)
    c.t = 5.0
    assert not b.try_acquire()


def test_concurrent_acquire_never_oversells() -> None:
    capacity = 50
    b = TokenBucket(capacity, 0, FakeClock())  # no refill, so exactly `capacity` can win
    wins: list[bool] = []
    barrier = threading.Barrier(200)

    def worker() -> None:
        barrier.wait()
        wins.append(b.try_acquire())

    threads = [threading.Thread(target=worker) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(wins) == capacity


def test_tenants_are_isolated_and_overrides_apply() -> None:
    lim = TenantLimiter(1, 0, overrides={"vip": (3, 0)}, clock=FakeClock())
    assert lim.allow("a") and not lim.allow("a")
    assert lim.allow("b")  # separate bucket
    assert [lim.allow("vip") for _ in range(4)] == [True, True, True, False]


def test_concurrent_first_use_creates_one_bucket_per_tenant() -> None:
    lim = TenantLimiter(10, 0, clock=FakeClock())
    wins: list[bool] = []
    barrier = threading.Barrier(100)

    def worker() -> None:
        barrier.wait()
        wins.append(lim.allow("t"))

    ts = [threading.Thread(target=worker) for _ in range(100)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(wins) == 10
