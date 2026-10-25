"""Лимит новых профилей с одного адреса: 20 в час, сверх — 429 с понятным сообщением."""

from uuid import UUID

import pytest

from app.core.errors import ErrorCode, TooManyProfilesError
from app.core.profiles import (
    PROFILE_CREATION_WINDOW_SECONDS,
    PROFILE_CREATIONS_PER_ADDRESS,
    ProfileOnboarding,
)
from app.core.rate_limit import SlidingWindowRateLimiter


class NoHistory:
    async def seed(self, storage: object, profile_id: UUID) -> None:
        """Истории нет: лимиту она не нужна."""


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_limit_is_twenty_per_hour() -> None:
    assert (PROFILE_CREATIONS_PER_ADDRESS, PROFILE_CREATION_WINDOW_SECONDS) == (20, 3600)


def test_rejects_creations_over_limit_from_same_address() -> None:
    onboarding = ProfileOnboarding(NoHistory())
    for _ in range(PROFILE_CREATIONS_PER_ADDRESS):
        onboarding.admit("203.0.113.5")

    with pytest.raises(TooManyProfilesError) as error:
        onboarding.admit("203.0.113.5")

    assert error.value.code is ErrorCode.RATE_LIMITED
    assert 0 < error.value.retry_after_seconds <= PROFILE_CREATION_WINDOW_SECONDS
    assert error.value.message == (
        "С вашего адреса создано слишком много профилей. Попробуйте снова через 60 мин."
    )
    onboarding.admit("203.0.113.6")


def test_window_slides() -> None:
    clock = FakeClock()
    onboarding = ProfileOnboarding(NoHistory(), SlidingWindowRateLimiter(2, 3600, clock=clock))
    onboarding.admit("ip")
    clock.now = 1800
    onboarding.admit("ip")

    with pytest.raises(TooManyProfilesError) as error:
        onboarding.admit("ip")

    assert error.value.retry_after_seconds == 1800
    assert "через 30 мин" in error.value.message
    clock.now = 3601
    onboarding.admit("ip")
