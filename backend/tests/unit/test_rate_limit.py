"""Ограничитель частоты со скользящим окном."""

import pytest

from app.core.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_allows_up_to_limit_then_blocks(clock: FakeClock) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=3, window_seconds=60, clock=clock)

    decisions = [limiter.hit("ip") for _ in range(4)]

    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert decisions[-1].retry_after_seconds == 60


def test_retry_after_counts_down_from_oldest_hit(clock: FakeClock) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=2, window_seconds=60, clock=clock)
    limiter.hit("ip")
    clock.now += 20
    limiter.hit("ip")
    clock.now += 10

    assert limiter.hit("ip").retry_after_seconds == 30


def test_allows_again_when_window_passes(clock: FakeClock) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=1, window_seconds=60, clock=clock)
    limiter.hit("ip")
    clock.now += 59.9
    assert not limiter.hit("ip").allowed

    clock.now += 0.1
    assert limiter.hit("ip").allowed


def test_rejected_hits_do_not_extend_block(clock: FakeClock) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=1, window_seconds=60, clock=clock)
    limiter.hit("ip")
    for _ in range(10):
        clock.now += 5
        limiter.hit("ip")

    clock.now += 10
    assert limiter.hit("ip").allowed


def test_keys_are_independent(clock: FakeClock) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=1, window_seconds=60, clock=clock)
    limiter.hit("first")

    assert limiter.hit("second").allowed


@pytest.mark.parametrize(("max_hits", "window_seconds"), [(0, 60), (1, 0), (-1, 10)])
def test_rejects_non_positive_limits(max_hits: int, window_seconds: float) -> None:
    with pytest.raises(ValueError, match="положительными"):
        SlidingWindowRateLimiter(max_hits=max_hits, window_seconds=window_seconds)
