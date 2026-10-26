"""Как пользователь назвал день и время — словарь, общий для LLM и кода.

LLM не считает даты: она только относит выражение к одному из видов (`DateKind`,
`DayPart`) и переписывает названные числа. Конкретные дату и время считает
`app.nlu.time_resolution` по правилам Q31.
"""

from dataclasses import dataclass
from enum import StrEnum


class DateKind(StrEnum):
    """Вид выражения дня или периода."""

    NONE = "none"
    """День не назван."""
    TODAY = "today"
    TOMORROW = "tomorrow"
    AFTER_TOMORROW = "after_tomorrow"
    YESTERDAY = "yesterday"
    MONDAY = "mon"
    """«в понедельник», «к понедельнику», «до понедельника»."""
    TUESDAY = "tue"
    WEDNESDAY = "wed"
    THURSDAY = "thu"
    FRIDAY = "fri"
    SATURDAY = "sat"
    SUNDAY = "sun"
    NEXT_MONDAY = "next_mon"
    """«в следующий понедельник», «в понедельник на следующей неделе»."""
    NEXT_TUESDAY = "next_tue"
    NEXT_WEDNESDAY = "next_wed"
    NEXT_THURSDAY = "next_thu"
    NEXT_FRIDAY = "next_fri"
    NEXT_SATURDAY = "next_sat"
    NEXT_SUNDAY = "next_sun"
    EXACT = "exact"
    """Число и месяц: «26 октября», «5.11» — «ДД.ММ» в `DateExpression.value`."""
    IN_DAYS = "in_days"
    """«через неделю», «через 3 дня» — число дней в `DateExpression.value`."""
    THIS_WEEK = "this_week"
    NEXT_WEEK = "next_week"
    LAST_WEEK = "last_week"
    END_OF_WEEK = "end_of_week"
    """«до конца недели»."""
    WEEKEND = "weekend"
    THIS_MONTH = "this_month"
    NEXT_MONTH = "next_month"
    LAST_MONTH = "last_month"
    END_OF_MONTH = "end_of_month"


WEEKDAY_KINDS: dict[DateKind, int] = {
    DateKind.MONDAY: 0,
    DateKind.TUESDAY: 1,
    DateKind.WEDNESDAY: 2,
    DateKind.THURSDAY: 3,
    DateKind.FRIDAY: 4,
    DateKind.SATURDAY: 5,
    DateKind.SUNDAY: 6,
}
"""День недели «в пятницу» → номер дня (пн = 0), как в `date.weekday()`."""

NEXT_WEEKDAY_KINDS: dict[DateKind, int] = {
    DateKind.NEXT_MONDAY: 0,
    DateKind.NEXT_TUESDAY: 1,
    DateKind.NEXT_WEDNESDAY: 2,
    DateKind.NEXT_THURSDAY: 3,
    DateKind.NEXT_FRIDAY: 4,
    DateKind.NEXT_SATURDAY: 5,
    DateKind.NEXT_SUNDAY: 6,
}
"""«В следующую пятницу» → номер дня недели на следующей неделе."""


class DayPart(StrEnum):
    """Часть суток: уточняет час («в 9 вечера») или заменяет время («вечером»)."""

    NONE = "none"
    MORNING = "morning"
    DAY = "day"
    """«днём», «в обед», «в 3 часа дня»."""
    EVENING = "evening"
    NIGHT = "night"


@dataclass(frozen=True, slots=True)
class DateExpression:
    """Названный день или период, ещё не переведённый в дату."""

    kind: DateKind = DateKind.NONE
    value: str = ""
    """Для `EXACT` — «ДД.ММ» или «ДД.ММ.ГГГГ», для `IN_DAYS` — число дней («7»)."""


@dataclass(frozen=True, slots=True)
class TimeExpression:
    """Названное время суток, ещё не приведённое к правилам Q31."""

    clock: str = ""
    """Время, как его назвали: «15:30», «3:00» (для «в 3»), пусто — не названо."""
    day_part: DayPart = DayPart.NONE
    in_minutes: int = 0
    """«через два часа» → 120; 0 — не названо."""
