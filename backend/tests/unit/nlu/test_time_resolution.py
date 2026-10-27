"""Правила дат и времени (решение Q31): каждое правило — отдельный тест."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.core.schedule import MOSCOW
from app.nlu.expressions import DateExpression, DateKind, DayPart, TimeExpression
from app.nlu.interfaces import Period, TimeScope, When
from app.nlu.time_resolution import (
    calendar_date,
    clock_time,
    in_moscow,
    moment_after,
    narrow_to_day_part,
    resolve_day,
    resolve_period,
    resolve_when,
    round_up_to_five_minutes,
    upcoming_weekday,
)

TUESDAY_NOON = dt.datetime(2026, 10, 27, 12, 0, tzinfo=MOSCOW)
FRIDAY_NOON = dt.datetime(2026, 10, 30, 12, 0, tzinfo=MOSCOW)
SUNDAY_NOON = dt.datetime(2026, 11, 1, 12, 0, tzinfo=MOSCOW)
FRIDAY = 4


def at(hour: int, minute: int = 0) -> dt.time:
    return dt.time(hour, minute)


def day(month: int, day_of_month: int, year: int = 2026) -> dt.date:
    return dt.date(year, month, day_of_month)


def midnight(month: int, day_of_month: int, year: int = 2026) -> dt.datetime:
    return dt.datetime(year, month, day_of_month, tzinfo=MOSCOW)


def when(kind: DateKind, clock: str = "", day_part: DayPart = DayPart.NONE) -> When | None:
    return resolve_when(DateExpression(kind), TimeExpression(clock, day_part), TUESDAY_NOON)


def period(kind: DateKind, now: dt.datetime = TUESDAY_NOON) -> Period | None:
    return resolve_period(DateExpression(kind), now)


# --- Части суток без часа ---------------------------------------------------------------


def test_morning_without_hour_is_nine() -> None:
    assert clock_time("", DayPart.MORNING) == at(9)


def test_daytime_and_lunch_without_hour_are_thirteen() -> None:
    assert clock_time("", DayPart.DAY) == at(13)


def test_evening_without_hour_is_nineteen() -> None:
    assert clock_time("", DayPart.EVENING) == at(19)


def test_night_without_hour_is_not_named() -> None:
    assert clock_time("", DayPart.NIGHT) is None


def test_nothing_named_is_no_time() -> None:
    assert clock_time("", DayPart.NONE) is None


# --- Час без уточнения: «в 3» ----------------------------------------------------------


@pytest.mark.parametrize("hour", range(1, 8))
def test_bare_hours_one_to_seven_are_afternoon(hour: int) -> None:
    assert clock_time(f"{hour}:00", DayPart.NONE) == at(hour + 12)


@pytest.mark.parametrize("hour", [0, 8, 9, 10, 11, 12])
def test_bare_hours_outside_one_to_seven_stay(hour: int) -> None:
    assert clock_time(f"{hour}:00", DayPart.NONE) == at(hour)


def test_twenty_four_hour_time_is_kept() -> None:
    assert clock_time("15:30", DayPart.NONE) == at(15, 30)


def test_minutes_survive_afternoon_shift() -> None:
    assert clock_time("2:30", DayPart.NONE) == at(14, 30)


@pytest.mark.parametrize("clock", ["3", "3.00", "3 ч 00"])
def test_clock_formats_are_understood(clock: str) -> None:
    assert clock_time(clock, DayPart.NONE) == at(15)


@pytest.mark.parametrize("clock", ["скоро", "25:00", "10:75", "-1"])
def test_unreadable_clock_is_not_named(clock: str) -> None:
    assert clock_time(clock, DayPart.NONE) is None


# --- Час с частью суток: «в 10 утра», «в 9 вечера» -------------------------------------


def test_morning_hour_is_kept() -> None:
    assert clock_time("7:00", DayPart.MORNING) == at(7)


def test_evening_hour_moves_to_afternoon() -> None:
    assert clock_time("9:00", DayPart.EVENING) == at(21)


def test_evening_hour_already_in_24h_is_kept() -> None:
    assert clock_time("21:00", DayPart.EVENING) == at(21)


def test_daytime_hour_three_is_fifteen() -> None:
    assert clock_time("3:00", DayPart.DAY) == at(15)


@pytest.mark.parametrize("hour", [11, 12])
def test_daytime_late_morning_hours_stay(hour: int) -> None:
    assert clock_time(f"{hour}:00", DayPart.DAY) == at(hour)


def test_eleven_at_night_is_twenty_three() -> None:
    assert clock_time("11:00", DayPart.NIGHT) == at(23)


def test_two_at_night_is_two() -> None:
    assert clock_time("2:00", DayPart.NIGHT) == at(2)


def test_twelve_at_night_is_midnight() -> None:
    assert clock_time("12:00", DayPart.NIGHT) == at(0)


# --- «Через N часов / минут» ------------------------------------------------------------


def test_in_two_hours_from_round_time() -> None:
    assert moment_after(TUESDAY_NOON, 120) == dt.datetime(2026, 10, 27, 14, 0, tzinfo=MOSCOW)


def test_in_hours_rounds_up_to_five_minutes() -> None:
    now = dt.datetime(2026, 10, 27, 12, 3, tzinfo=MOSCOW)

    assert moment_after(now, 120) == dt.datetime(2026, 10, 27, 14, 5, tzinfo=MOSCOW)


def test_rounding_never_goes_back_in_time() -> None:
    moment = dt.datetime(2026, 10, 27, 12, 15, 30, tzinfo=MOSCOW)

    assert round_up_to_five_minutes(moment) == dt.datetime(2026, 10, 27, 12, 20, tzinfo=MOSCOW)


def test_round_moment_is_not_moved() -> None:
    assert round_up_to_five_minutes(TUESDAY_NOON) == TUESDAY_NOON


def test_in_minutes_crosses_midnight() -> None:
    late = dt.datetime(2026, 10, 27, 23, 50, tzinfo=MOSCOW)

    assert moment_after(late, 30) == dt.datetime(2026, 10, 28, 0, 20, tzinfo=MOSCOW)


def test_in_minutes_overrides_named_day() -> None:
    expression = TimeExpression(in_minutes=15)

    assert resolve_when(DateExpression(DateKind.TOMORROW), expression, TUESDAY_NOON) == When(
        date=day(10, 27), time=at(12, 15)
    )


# --- Дни: «в пятницу», «в следующую пятницу», «через неделю» --------------------------


def test_weekday_is_nearest_future_one() -> None:
    assert when(DateKind.FRIDAY) == When(date=day(10, 30))


def test_same_weekday_is_today_while_time_not_passed() -> None:
    assert upcoming_weekday(FRIDAY_NOON, FRIDAY, at(15)) == day(10, 30)


def test_same_weekday_moves_a_week_when_time_passed() -> None:
    assert upcoming_weekday(FRIDAY_NOON, FRIDAY, at(10)) == day(11, 6)


def test_same_weekday_without_time_is_next_week() -> None:
    assert upcoming_weekday(FRIDAY_NOON, FRIDAY) == day(11, 6)


def test_same_weekday_exactly_at_named_time_is_next_week() -> None:
    assert upcoming_weekday(FRIDAY_NOON, FRIDAY, at(12)) == day(11, 6)


def friday_when(clock: str = "", day_part: DayPart = DayPart.NONE) -> When | None:
    """«в пятницу …», сказанное в пятницу в полдень: создание или новая дата переноса."""
    return resolve_when(
        DateExpression(DateKind.FRIDAY), TimeExpression(clock, day_part), FRIDAY_NOON
    )


def test_new_date_on_same_weekday_without_time_is_next_week() -> None:
    assert friday_when() == When(date=day(11, 6))


def test_new_date_on_same_weekday_with_time_ahead_is_today() -> None:
    assert friday_when("15:00") == When(date=day(10, 30), time=at(15))


def test_new_date_on_same_weekday_with_passed_time_is_next_week() -> None:
    assert friday_when("10:00") == When(date=day(11, 6), time=at(10))


def test_new_date_on_same_weekday_with_day_part_ahead_is_today() -> None:
    assert friday_when(day_part=DayPart.EVENING) == When(date=day(10, 30), time=at(19))


def test_same_weekday_in_list_is_today() -> None:
    assert period(DateKind.FRIDAY, now=FRIDAY_NOON) == Period(
        midnight(10, 30), midnight(10, 31), "на пятницу, 30 октября"
    )


def test_same_weekday_of_existing_record_is_today() -> None:
    expression = DateExpression(DateKind.FRIDAY)

    assert resolve_when(expression, TimeExpression(), FRIDAY_NOON, TimeScope.ANY) == When(
        date=day(10, 30)
    )


def test_next_weekday_is_in_next_calendar_week() -> None:
    assert when(DateKind.NEXT_FRIDAY) == When(date=day(11, 6))
    assert when(DateKind.NEXT_MONDAY) == When(date=day(11, 2))


def test_past_scope_takes_last_passed_weekday() -> None:
    expression = DateExpression(DateKind.FRIDAY)

    assert resolve_day(expression, TUESDAY_NOON, TimeScope.PAST) == day(10, 23)


def test_today_tomorrow_after_tomorrow_yesterday() -> None:
    assert when(DateKind.TODAY) == When(date=day(10, 27))
    assert when(DateKind.TOMORROW) == When(date=day(10, 28))
    assert when(DateKind.AFTER_TOMORROW) == When(date=day(10, 29))
    assert when(DateKind.YESTERDAY) == When(date=day(10, 26))


def test_in_days_counts_from_today() -> None:
    expression = DateExpression(DateKind.IN_DAYS, value="7")

    assert resolve_when(expression, TimeExpression(), TUESDAY_NOON) == When(date=day(11, 3))


@pytest.mark.parametrize("value", ["", "0", "неделя"])
def test_in_days_without_number_is_not_named(value: str) -> None:
    expression = DateExpression(DateKind.IN_DAYS, value=value)

    assert resolve_when(expression, TimeExpression(), TUESDAY_NOON) is None


# --- Число и месяц: «26 ноября» --------------------------------------------------------


def test_calendar_date_in_future_this_year() -> None:
    assert calendar_date("26.11", day(10, 27), TimeScope.FUTURE) == day(11, 26)


def test_passed_calendar_date_moves_to_next_year_for_new_records() -> None:
    assert calendar_date("26.10", day(10, 27), TimeScope.FUTURE) == day(10, 26, year=2027)


def test_calendar_date_for_lists_is_nearest() -> None:
    assert calendar_date("20.10", day(10, 27), TimeScope.ANY) == day(10, 20)


def test_calendar_date_for_past_scope_is_not_in_future() -> None:
    assert calendar_date("26.12", day(10, 27), TimeScope.PAST) == day(12, 26, year=2025)


def test_calendar_date_with_year_is_kept() -> None:
    assert calendar_date("05.01.2027", day(10, 27), TimeScope.ANY) == day(1, 5, year=2027)


@pytest.mark.parametrize("value", ["31.02", "завтра", "", "32.10"])
def test_impossible_calendar_date_is_not_named(value: str) -> None:
    assert calendar_date(value, day(10, 27), TimeScope.FUTURE) is None


# --- Недели: «до конца недели», «на следующей неделе», «на выходных» -------------------


def test_end_of_week_is_sunday_2359() -> None:
    assert when(DateKind.END_OF_WEEK) == When(date=day(11, 1), time=at(23, 59))


def test_end_of_week_keeps_named_time() -> None:
    assert when(DateKind.END_OF_WEEK, "18:00") == When(date=day(11, 1), time=at(18))


def test_end_of_week_on_sunday_is_today() -> None:
    expression = DateExpression(DateKind.END_OF_WEEK)

    assert resolve_when(expression, TimeExpression(), SUNDAY_NOON) == When(
        date=day(11, 1), time=at(23, 59)
    )


def test_next_week_names_only_the_week() -> None:
    assert when(DateKind.NEXT_WEEK) == When(week_of=day(11, 2))


def test_this_week_names_current_monday() -> None:
    assert when(DateKind.THIS_WEEK) == When(week_of=day(10, 26))


def test_weekend_is_saturday() -> None:
    assert when(DateKind.WEEKEND) == When(date=day(10, 31))


def test_weekend_on_sunday_is_today() -> None:
    expression = DateExpression(DateKind.WEEKEND)

    assert resolve_when(expression, TimeExpression(), SUNDAY_NOON) == When(date=day(11, 1))


def test_end_of_month_is_last_day_2359() -> None:
    assert when(DateKind.END_OF_MONTH) == When(date=day(10, 31), time=at(23, 59))


# --- Что названо, то и в When ------------------------------------------------------------


def test_nothing_named_gives_no_when() -> None:
    assert when(DateKind.NONE) is None


def test_only_time_named_leaves_date_empty() -> None:
    assert when(DateKind.NONE, "15:00") == When(time=at(15))


def test_day_named_without_time_leaves_time_empty() -> None:
    assert when(DateKind.TOMORROW) == When(date=day(10, 28), time=None)


def test_month_without_day_gives_no_when() -> None:
    assert when(DateKind.NEXT_MONTH) is None


# --- Периоды для списков ---------------------------------------------------------------


def test_today_period() -> None:
    assert period(DateKind.TODAY) == Period(midnight(10, 27), midnight(10, 28), "сегодня")


def test_tomorrow_period() -> None:
    assert period(DateKind.TOMORROW) == Period(midnight(10, 28), midnight(10, 29), "на завтра")


def test_after_tomorrow_period() -> None:
    assert period(DateKind.AFTER_TOMORROW) == Period(
        midnight(10, 29), midnight(10, 30), "на послезавтра"
    )


def test_specific_day_period_is_labelled_with_date() -> None:
    assert period(DateKind.FRIDAY) == Period(
        midnight(10, 30), midnight(10, 31), "на пятницу, 30 октября"
    )


def test_this_week_is_monday_to_sunday() -> None:
    assert period(DateKind.THIS_WEEK) == Period(midnight(10, 26), midnight(11, 2), "на этой неделе")


def test_next_week_period() -> None:
    assert period(DateKind.NEXT_WEEK) == Period(
        midnight(11, 2), midnight(11, 9), "на следующей неделе"
    )


def test_last_week_period() -> None:
    assert period(DateKind.LAST_WEEK) == Period(
        midnight(10, 19), midnight(10, 26), "на прошлой неделе"
    )


def test_weekend_period_is_saturday_and_sunday() -> None:
    assert period(DateKind.WEEKEND) == Period(midnight(10, 31), midnight(11, 2), "на выходных")


def test_end_of_week_period_starts_today() -> None:
    assert period(DateKind.END_OF_WEEK) == Period(
        midnight(10, 27), midnight(11, 2), "до конца недели"
    )


def test_this_month_period() -> None:
    assert period(DateKind.THIS_MONTH) == Period(midnight(10, 1), midnight(11, 1), "в этом месяце")


def test_next_month_crosses_year() -> None:
    december = dt.datetime(2026, 12, 15, 12, 0, tzinfo=MOSCOW)

    assert period(DateKind.NEXT_MONTH, december) == Period(
        midnight(1, 1, year=2027), midnight(2, 1, year=2027), "в следующем месяце"
    )


def test_last_month_crosses_year() -> None:
    january = dt.datetime(2027, 1, 10, 12, 0, tzinfo=MOSCOW)

    assert period(DateKind.LAST_MONTH, january) == Period(
        midnight(12, 1), midnight(1, 1, year=2027), "в прошлом месяце"
    )


def test_no_period_named() -> None:
    assert period(DateKind.NONE) is None


# --- Часовой пояс -------------------------------------------------------------------------


def test_naive_now_is_moscow() -> None:
    assert in_moscow(dt.datetime(2026, 10, 27, 12, 0)) == TUESDAY_NOON


def test_now_in_other_zone_is_converted_to_moscow() -> None:
    late_utc = dt.datetime(2026, 10, 27, 22, 30, tzinfo=ZoneInfo("UTC"))
    expression = DateExpression(DateKind.TODAY)

    assert resolve_when(expression, TimeExpression(), late_utc) == When(date=day(10, 28))


# --- Часть суток в списке: «что у меня завтра вечером» ---------------------------------


def period_of(kind: DateKind) -> Period:
    found = period(kind)
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("day_part", "first_hour", "last_hour", "label"),
    [
        (DayPart.MORNING, 6, 12, "завтра утром"),
        (DayPart.DAY, 12, 18, "завтра днём"),
        (DayPart.EVENING, 18, 24, "завтра вечером"),
        (DayPart.NIGHT, 0, 6, "завтра ночью"),
    ],
)
def test_day_part_narrows_one_day(
    day_part: DayPart, first_hour: int, last_hour: int, label: str
) -> None:
    start = midnight(10, 28)

    narrowed = narrow_to_day_part(period_of(DateKind.TOMORROW), day_part, TUESDAY_NOON)

    assert narrowed == Period(
        start + dt.timedelta(hours=first_hour), start + dt.timedelta(hours=last_hour), label
    )


@pytest.mark.parametrize(
    ("day_part", "default_time"),
    [(DayPart.MORNING, at(9)), (DayPart.DAY, at(13)), (DayPart.EVENING, at(19))],
)
def test_q31_default_time_lies_inside_its_day_part(
    day_part: DayPart, default_time: dt.time
) -> None:
    narrowed = narrow_to_day_part(period_of(DateKind.TODAY), day_part, TUESDAY_NOON)
    moment = dt.datetime.combine(day(10, 27), default_time, tzinfo=MOSCOW)

    assert narrowed.start <= moment < narrowed.end


def test_day_part_label_today() -> None:
    narrowed = narrow_to_day_part(period_of(DateKind.TODAY), DayPart.EVENING, TUESDAY_NOON)

    assert narrowed.label == "сегодня вечером"


def test_day_part_label_for_named_weekday() -> None:
    narrowed = narrow_to_day_part(period_of(DateKind.FRIDAY), DayPart.MORNING, TUESDAY_NOON)

    assert narrowed.label == "в пятницу, 30 октября, утром"


def test_day_part_label_uses_vo_before_tuesday() -> None:
    next_tuesday = period(DateKind.NEXT_TUESDAY)
    assert next_tuesday is not None

    narrowed = narrow_to_day_part(next_tuesday, DayPart.DAY, TUESDAY_NOON)

    assert narrowed.label == "во вторник, 3 ноября, днём"


def test_without_day_part_period_is_unchanged() -> None:
    tomorrow = period_of(DateKind.TOMORROW)

    assert narrow_to_day_part(tomorrow, DayPart.NONE, TUESDAY_NOON) == tomorrow


def test_day_part_does_not_narrow_a_week() -> None:
    week = period_of(DateKind.THIS_WEEK)

    assert narrow_to_day_part(week, DayPart.EVENING, TUESDAY_NOON) == week
