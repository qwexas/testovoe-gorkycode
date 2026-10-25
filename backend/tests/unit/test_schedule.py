"""Время записи: Москва, «только дата», длительность встречи, обязательные поля (Q30, Q31)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import EventType
from app.core.errors import EventValidationError
from app.core.schedule import MOSCOW, Schedule, settle_schedule, start_of_day

TOMORROW_15 = datetime(2026, 10, 27, 15, 0, tzinfo=MOSCOW)


def test_time_is_converted_to_moscow() -> None:
    settled = settle_schedule(
        EventType.TASK, Schedule(datetime(2026, 10, 27, 12, 0, tzinfo=UTC), has_time=True)
    )

    assert settled.starts_at == TOMORROW_15
    assert settled.starts_at is not None
    assert settled.starts_at.utcoffset() == timedelta(hours=3)


def test_date_only_resets_time_to_moscow_midnight() -> None:
    late_evening_utc = datetime(2026, 10, 26, 22, 30, tzinfo=UTC)

    settled = settle_schedule(EventType.TASK, Schedule(late_evening_utc, has_time=False))

    assert settled.starts_at == datetime(2026, 10, 27, 0, 0, tzinfo=MOSCOW)
    assert settled.has_time is False


def test_task_without_date_has_no_time() -> None:
    settled = settle_schedule(EventType.TASK, Schedule(None, has_time=True))

    assert settled == Schedule(None, has_time=False, ends_at=None)


def test_meeting_lasts_an_hour_by_default() -> None:
    settled = settle_schedule(EventType.MEETING, Schedule(TOMORROW_15, has_time=True))

    assert settled.ends_at == TOMORROW_15 + timedelta(minutes=60)


def test_meeting_keeps_explicit_end() -> None:
    end = TOMORROW_15 + timedelta(minutes=30)

    settled = settle_schedule(EventType.MEETING, Schedule(TOMORROW_15, True, end))

    assert settled.ends_at == end


def test_meeting_may_end_when_it_starts() -> None:
    settled = settle_schedule(EventType.MEETING, Schedule(TOMORROW_15, True, TOMORROW_15))

    assert settled.ends_at == TOMORROW_15


def test_meeting_cannot_end_before_start() -> None:
    with pytest.raises(EventValidationError, match="раньше"):
        settle_schedule(
            EventType.MEETING,
            Schedule(TOMORROW_15, True, TOMORROW_15 - timedelta(minutes=1)),
        )


@pytest.mark.parametrize("event_type", [EventType.TASK, EventType.REMINDER])
def test_only_meeting_has_end(event_type: EventType) -> None:
    with pytest.raises(EventValidationError, match="только у встречи"):
        settle_schedule(event_type, Schedule(TOMORROW_15, True, TOMORROW_15 + timedelta(hours=1)))


@pytest.mark.parametrize(
    ("event_type", "schedule"),
    [
        (EventType.MEETING, Schedule(None, has_time=True)),
        (EventType.MEETING, Schedule(TOMORROW_15, has_time=False)),
        (EventType.REMINDER, Schedule(None, has_time=True)),
        (EventType.REMINDER, Schedule(TOMORROW_15, has_time=False)),
    ],
)
def test_meeting_and_reminder_need_date_and_time(event_type: EventType, schedule: Schedule) -> None:
    with pytest.raises(EventValidationError, match="дата и время"):
        settle_schedule(event_type, schedule)


def test_start_of_day_uses_moscow_date() -> None:
    assert start_of_day(datetime(2026, 10, 26, 21, 0, tzinfo=UTC)) == datetime(
        2026, 10, 27, tzinfo=MOSCOW
    )
