"""Время записи: часовой пояс, «только дата», длительность встречи и проверка полей.

Правила общие для интерфейса, голоса и импорта истории: что обязательно у встречи
и напоминания — решение Q30, длительность встречи по умолчанию — Q31.
"""

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.enums import EventType
from app.core.errors import EventValidationError

PROFILE_TIMEZONE = "Europe/Moscow"
MOSCOW = ZoneInfo(PROFILE_TIMEZONE)
DEFAULT_MEETING_DURATION = timedelta(minutes=60)

TYPES_WITH_REQUIRED_TIME = {
    EventType.MEETING: "У встречи должны быть дата и время.",
    EventType.REMINDER: "У напоминания должны быть дата и время.",
}
END_ONLY_FOR_MEETING = "Время окончания бывает только у встречи."
END_BEFORE_START = "Встреча не может закончиться раньше, чем началась."


@dataclass(frozen=True, slots=True)
class Schedule:
    """Когда запись: начало (срок), есть ли у него время и конец встречи."""

    starts_at: datetime | None
    has_time: bool
    ends_at: datetime | None = None


def settle_schedule(event_type: EventType, schedule: Schedule) -> Schedule:
    """Приводит время записи к правилам и проверяет его.

    Время переводится в Europe/Moscow; без времени (`has_time=False`) начало — 00:00
    по Москве; у встречи без конца конец = начало + 60 минут.

    Raises:
        EventValidationError: Не хватает даты и времени или конец не подходит.
    """
    settled = _drop_time_if_absent(_in_profile_timezone(schedule))
    _check_required_time(event_type, settled)
    if event_type is not EventType.MEETING:
        _check_no_end(settled)
        return settled
    with_end = _with_default_end(settled)
    _check_end_after_start(with_end)
    return with_end


def moscow_now() -> datetime:
    """Текущий момент по Москве."""
    return datetime.now(MOSCOW)


def start_of_day(moment: datetime) -> datetime:
    """Полночь по Москве того дня, на который приходится `moment`."""
    return datetime.combine(moment.astimezone(MOSCOW).date(), time.min, tzinfo=MOSCOW)


def _in_profile_timezone(schedule: Schedule) -> Schedule:
    return replace(
        schedule,
        starts_at=_to_moscow(schedule.starts_at),
        ends_at=_to_moscow(schedule.ends_at),
    )


def _to_moscow(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(MOSCOW)


def _drop_time_if_absent(schedule: Schedule) -> Schedule:
    if schedule.starts_at is None:
        return replace(schedule, has_time=False)
    if schedule.has_time:
        return schedule
    return replace(schedule, starts_at=start_of_day(schedule.starts_at))


def _check_required_time(event_type: EventType, schedule: Schedule) -> None:
    message = TYPES_WITH_REQUIRED_TIME.get(event_type)
    if message is not None and not schedule.has_time:
        raise EventValidationError(message)


def _check_no_end(schedule: Schedule) -> None:
    if schedule.ends_at is not None:
        raise EventValidationError(END_ONLY_FOR_MEETING)


def _with_default_end(schedule: Schedule) -> Schedule:
    if schedule.ends_at is not None or schedule.starts_at is None:
        return schedule
    return replace(schedule, ends_at=schedule.starts_at + DEFAULT_MEETING_DURATION)


def _check_end_after_start(schedule: Schedule) -> None:
    if schedule.starts_at is None or schedule.ends_at is None:
        return
    if schedule.ends_at < schedule.starts_at:
        raise EventValidationError(END_BEFORE_START)
