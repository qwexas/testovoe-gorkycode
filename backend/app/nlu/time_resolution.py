"""Перевод названных дня и времени в конкретные значения — правила решения Q31.

Чистые функции без LLM и ввода-вывода: на вход — выражение (`DateExpression`,
`TimeExpression`) и текущий момент, на выход — `When` или `Period`. Всё по Москве.

Правила:
- «утром» 09:00, «днём» / «в обед» 13:00, «вечером» 19:00;
- «в 3» без уточнения: часы 1-7 — дневные (15:00), «в 9 вечера» — 21:00;
- «через N часов / минут» — сейчас + N, вверх до ближайших 5 минут;
- «в пятницу» — ближайшая пятница; если сегодня пятница — сегодня, пока названное
  время не прошло (см. `upcoming_weekday`); «в следующую пятницу» — пятница следующей недели;
- «до конца недели» — воскресенье 23:59; «на следующей неделе» — только неделя (`week_of`);
- периоды списков — полуинтервалы `[начало, конец)`: день, неделя пн-вс, выходные, месяц.
"""

import datetime as dt
import re
from calendar import monthrange

from app.core.schedule import MOSCOW
from app.nlu.expressions import (
    NEXT_WEEKDAY_KINDS,
    WEEKDAY_KINDS,
    DateExpression,
    DateKind,
    DayPart,
    TimeExpression,
)
from app.nlu.interfaces import Period, TimeScope, When

ROUNDING_MINUTES = 5
DAYS_IN_WEEK = 7
SATURDAY = 5
NOON_HOUR = 12
AFTERNOON_HOURS = range(1, 8)
"""«в 3» без уточнения — 15:00: встречи и звонки в 3 часа ночи редки (Q31)."""
DAYTIME_HOURS = range(1, 8)
"""«в 2 часа дня» — 14:00, но «в 11 дня» — 11:00."""
LATE_NIGHT_HOURS = range(9, 12)
"""«в 11 ночи» — 23:00, а «в 2 ночи» — 02:00."""

DAY_PART_DEFAULTS: dict[DayPart, dt.time] = {
    DayPart.MORNING: dt.time(9, 0),
    DayPart.DAY: dt.time(13, 0),
    DayPart.EVENING: dt.time(19, 0),
}
"""Время, если названа только часть суток. «Ночью» правила Q31 не задают — время пустое."""
END_OF_DAY = dt.time(23, 59)
"""Срок «до конца недели / месяца»."""

MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS_ACCUSATIVE = (
    "понедельник",
    "вторник",
    "среду",
    "четверг",
    "пятницу",
    "субботу",
    "воскресенье",
)

_CLOCK = re.compile(r"^\s*(\d{1,2})(?:\s*[:.ч]\s*(\d{1,2}))?\s*$")
_DAY_MONTH = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\s*$")
_ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")

DAY_LABELS: dict[DateKind, str] = {
    DateKind.TODAY: "сегодня",
    DateKind.TOMORROW: "на завтра",
    DateKind.AFTER_TOMORROW: "на послезавтра",
    DateKind.YESTERDAY: "вчера",
}
RANGE_LABELS: dict[DateKind, str] = {
    DateKind.THIS_WEEK: "на этой неделе",
    DateKind.NEXT_WEEK: "на следующей неделе",
    DateKind.LAST_WEEK: "на прошлой неделе",
    DateKind.END_OF_WEEK: "до конца недели",
    DateKind.WEEKEND: "на выходных",
    DateKind.THIS_MONTH: "в этом месяце",
    DateKind.NEXT_MONTH: "в следующем месяце",
    DateKind.LAST_MONTH: "в прошлом месяце",
    DateKind.END_OF_MONTH: "до конца месяца",
}


def in_moscow(moment: dt.datetime) -> dt.datetime:
    """Момент по Москве; наивное время считается московским."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MOSCOW)
    return moment.astimezone(MOSCOW)


def round_up_to_five_minutes(moment: dt.datetime) -> dt.datetime:
    """Вверх до ближайших 5 минут без секунд: 12:03 → 12:05, 12:05 → 12:05.

    Вверх, а не к ближайшему: напоминание «через час» не должно сработать раньше часа.
    """
    whole_minute = moment.replace(second=0, microsecond=0)
    if whole_minute < moment:
        whole_minute += dt.timedelta(minutes=1)
    remainder = whole_minute.minute % ROUNDING_MINUTES
    if remainder == 0:
        return whole_minute
    return whole_minute + dt.timedelta(minutes=ROUNDING_MINUTES - remainder)


def moment_after(now: dt.datetime, minutes: int) -> dt.datetime:
    """«Через N минут / часов»: сейчас + N с округлением вверх до 5 минут."""
    return round_up_to_five_minutes(in_moscow(now) + dt.timedelta(minutes=minutes))


def clock_time(clock: str, day_part: DayPart) -> dt.time | None:
    """Время суток по названному часу и части суток (Q31).

    «15:30» → 15:30; «3» → 15:00; «9» + вечер → 21:00; «10» + утро → 10:00;
    пустое время + «вечером» → 19:00. Непонятное значение — `None` (не названо).
    """
    match = _CLOCK.match(clock)
    if match is None:
        return DAY_PART_DEFAULTS.get(day_part)
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour == 24 and minute == 0:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return dt.time(_hour_in_day_part(hour, day_part), minute)


def _hour_in_day_part(hour: int, day_part: DayPart) -> int:
    match day_part:
        case DayPart.NONE if hour in AFTERNOON_HOURS:
            return hour + NOON_HOUR
        case DayPart.DAY if hour in DAYTIME_HOURS:
            return hour + NOON_HOUR
        case DayPart.EVENING if 0 < hour < NOON_HOUR:
            return hour + NOON_HOUR
        case DayPart.NIGHT if hour in LATE_NIGHT_HOURS:
            return hour + NOON_HOUR
        case DayPart.NIGHT if hour == NOON_HOUR:
            return 0
        case _:
            return hour


def week_start(day: dt.date) -> dt.date:
    """Понедельник недели, в которую входит `day`."""
    return day - dt.timedelta(days=day.weekday())


def upcoming_weekday(now: dt.datetime, weekday: int, at: dt.time | None = None) -> dt.date:
    """Ближайший будущий день недели: «в пятницу».

    Если сегодня этот день, выбирается сегодня, пока названное время `at` не прошло
    (без времени — весь день). Ошибка «сегодня вместо через неделю» видна сразу в
    подтверждении и безобидна, а обратная — пропущенная встреча сегодня.
    """
    current = in_moscow(now)
    today = current.date()
    day = today + dt.timedelta(days=(weekday - today.weekday()) % DAYS_IN_WEEK)
    if day == today and at is not None and at <= current.time():
        day += dt.timedelta(days=DAYS_IN_WEEK)
    return day


def recent_weekday(today: dt.date, weekday: int) -> dt.date:
    """Последний прошедший (или сегодняшний) день недели: «что было в пятницу»."""
    return today - dt.timedelta(days=(today.weekday() - weekday) % DAYS_IN_WEEK)


def weekday_next_week(today: dt.date, weekday: int) -> dt.date:
    """«В следующую пятницу» — пятница следующей календарной недели."""
    return week_start(today) + dt.timedelta(days=DAYS_IN_WEEK + weekday)


def calendar_date(exact: str, today: dt.date, scope: TimeScope) -> dt.date | None:
    """«26.10» или «26.10.2027» → дата; без года — ближайшая по смыслу `scope`.

    `FUTURE` — сегодня или позже (создание записи), `PAST` — сегодня или раньше,
    `ANY` — ближайшая к сегодняшнему дню. Несуществующая дата — `None`.
    """
    parsed = _parse_calendar_date(exact)
    if parsed is None:
        return None
    day, month, year = parsed
    if year is not None:
        return _safe_date(year, month, day)
    candidates = [
        candidate
        for candidate in (_safe_date(today.year + shift, month, day) for shift in (-1, 0, 1))
        if candidate is not None
    ]
    if scope is TimeScope.FUTURE:
        return min((c for c in candidates if c >= today), default=None)
    if scope is TimeScope.PAST:
        return max((c for c in candidates if c <= today), default=None)
    return min(candidates, key=lambda candidate: abs((candidate - today).days), default=None)


def _parse_calendar_date(exact: str) -> tuple[int, int, int | None] | None:
    if match := _DAY_MONTH.match(exact):
        year = int(match.group(3)) if match.group(3) else None
        return int(match.group(1)), int(match.group(2)), year
    if match := _ISO_DATE.match(exact):
        return int(match.group(3)), int(match.group(2)), int(match.group(1))
    return None


def _positive_number(text: str) -> int | None:
    stripped = text.strip()
    return int(stripped) if stripped.isdecimal() and int(stripped) > 0 else None


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def resolve_day(
    expression: DateExpression, now: dt.datetime, scope: TimeScope, at: dt.time | None = None
) -> dt.date | None:
    """Один конкретный день, если выражение его называет («завтра», «в пятницу», «26.10»).

    Для недель и месяцев — `None`: это периоды, а не день.
    """
    today = in_moscow(now).date()
    kind = expression.kind
    if kind in WEEKDAY_KINDS:
        weekday = WEEKDAY_KINDS[kind]
        if scope is TimeScope.PAST:
            return recent_weekday(today, weekday)
        return upcoming_weekday(now, weekday, at if scope is TimeScope.FUTURE else None)
    if kind in NEXT_WEEKDAY_KINDS:
        return weekday_next_week(today, NEXT_WEEKDAY_KINDS[kind])
    match kind:
        case DateKind.TODAY:
            return today
        case DateKind.TOMORROW:
            return today + dt.timedelta(days=1)
        case DateKind.AFTER_TOMORROW:
            return today + dt.timedelta(days=2)
        case DateKind.YESTERDAY:
            return today - dt.timedelta(days=1)
        case DateKind.EXACT:
            return calendar_date(expression.value, today, scope)
        case DateKind.IN_DAYS:
            days = _positive_number(expression.value)
            return None if days is None else today + dt.timedelta(days=days)
        case _:
            return None


def resolve_when(
    date_expression: DateExpression,
    time_expression: TimeExpression,
    now: dt.datetime,
    scope: TimeScope = TimeScope.FUTURE,
) -> When | None:
    """Когда: для создания, переноса, ответа на уточнение. `None` — ничего не названо.

    Названное остаётся названным, не названное — пустым: дату к одному времени
    («в 15:00») парсер не придумывает, это решает бизнес-логика.
    """
    if time_expression.in_minutes > 0:
        moment = moment_after(now, time_expression.in_minutes)
        return When(date=moment.date(), time=moment.time())
    at = clock_time(time_expression.clock, time_expression.day_part)
    today = in_moscow(now).date()
    match date_expression.kind:
        case DateKind.THIS_WEEK | DateKind.NEXT_WEEK | DateKind.LAST_WEEK:
            start = week_start(today) + _week_shift(date_expression.kind)
            when = When(time=at, week_of=start)
        case DateKind.END_OF_WEEK:
            sunday = week_start(today) + dt.timedelta(days=DAYS_IN_WEEK - 1)
            when = When(date=sunday, time=at or END_OF_DAY)
        case DateKind.END_OF_MONTH:
            when = When(date=_month_end(today), time=at or END_OF_DAY)
        case DateKind.WEEKEND:
            when = When(date=max(today, week_start(today) + dt.timedelta(days=SATURDAY)), time=at)
        case _:
            when = When(date=resolve_day(date_expression, now, scope, at), time=at)
    return None if when.is_empty else when


def resolve_period(
    expression: DateExpression, now: dt.datetime, scope: TimeScope = TimeScope.ANY
) -> Period | None:
    """Период для списка или фильтра поиска; `None` — период не назван."""
    today = in_moscow(now).date()
    kind = expression.kind
    if kind in RANGE_LABELS:
        start, end = _range_bounds(kind, today)
        return Period(start=_midnight(start), end=_midnight(end), label=RANGE_LABELS[kind])
    day = resolve_day(expression, now, scope)
    if day is None:
        return None
    return Period(
        start=_midnight(day),
        end=_midnight(day + dt.timedelta(days=1)),
        label=DAY_LABELS.get(kind) or day_label(day),
    )


def day_label(day: dt.date) -> str:
    """«на пятницу, 30 октября»."""
    weekday = WEEKDAYS_ACCUSATIVE[day.weekday()]
    return f"на {weekday}, {day.day} {MONTHS_GENITIVE[day.month - 1]}"


def _range_bounds(kind: DateKind, today: dt.date) -> tuple[dt.date, dt.date]:
    monday = week_start(today)
    week = dt.timedelta(days=DAYS_IN_WEEK)
    match kind:
        case DateKind.THIS_WEEK | DateKind.NEXT_WEEK | DateKind.LAST_WEEK:
            start = monday + _week_shift(kind)
            return start, start + week
        case DateKind.END_OF_WEEK:
            return today, monday + week
        case DateKind.WEEKEND:
            return monday + dt.timedelta(days=SATURDAY), monday + week
        case DateKind.THIS_MONTH:
            return today.replace(day=1), _next_month_start(today)
        case DateKind.NEXT_MONTH:
            start = _next_month_start(today)
            return start, _next_month_start(start)
        case DateKind.LAST_MONTH:
            end = today.replace(day=1)
            return (end - dt.timedelta(days=1)).replace(day=1), end
        case DateKind.END_OF_MONTH:
            return today, _next_month_start(today)
        case _:
            raise ValueError(f"{kind} — не период")


def _week_shift(kind: DateKind) -> dt.timedelta:
    weeks = {DateKind.NEXT_WEEK: 1, DateKind.LAST_WEEK: -1}.get(kind, 0)
    return dt.timedelta(days=DAYS_IN_WEEK * weeks)


def _next_month_start(day: dt.date) -> dt.date:
    return _month_end(day) + dt.timedelta(days=1)


def _month_end(day: dt.date) -> dt.date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def _midnight(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=MOSCOW)
