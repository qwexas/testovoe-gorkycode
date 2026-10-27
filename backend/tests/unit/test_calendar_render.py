"""Календарь iCalendar: файл разбирается обратно, время по Москве, предупреждения на месте."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from icalendar import Calendar, Event

from app.core.calendar import render_calendar
from app.core.enums import EventSource, EventStatus, EventType
from app.core.events import EventCard
from app.core.schedule import MOSCOW
from tests.unit.dialog.support import NOW, TOMORROW, at

FRIDAY = date(2026, 10, 30)


def card(
    event_id: int, event_type: EventType, starts_at: datetime | None, **fields: Any
) -> EventCard:
    values: dict[str, Any] = {
        "id": event_id,
        "type": event_type,
        "title": f"Запись {event_id}",
        "starts_at": starts_at,
        "has_time": starts_at is not None,
        "ends_at": None,
        "status": EventStatus.OPEN,
        "source": EventSource.USER,
        "created_at": NOW - timedelta(days=1),
        "updated_at": NOW,
    }
    return EventCard(**(values | fields))


def parse(*cards: EventCard) -> Calendar:
    return Calendar.from_ical(render_calendar(cards, NOW))


def only_event(calendar: Calendar) -> Event:
    [event] = calendar.walk("VEVENT")
    return event


def alarm_trigger(event: Event) -> timedelta:
    [alarm] = event.walk("VALARM")
    assert alarm["ACTION"] == "DISPLAY"
    assert str(alarm["DESCRIPTION"]) == str(event["SUMMARY"])
    trigger: timedelta = alarm.decoded("TRIGGER")
    return trigger


class TestCalendarProperties:
    def test_publishes_named_calendar_in_moscow_time(self) -> None:
        calendar = parse()

        assert calendar["VERSION"] == "2.0"
        assert calendar["PRODID"] == "-//GORKYCODE//Gorky voice assistant//RU"
        assert calendar["METHOD"] == "PUBLISH"
        assert calendar["CALSCALE"] == "GREGORIAN"
        assert str(calendar["X-WR-CALNAME"]) == "Горький"
        assert str(calendar["X-WR-TIMEZONE"]) == "Europe/Moscow"
        assert calendar.decoded("REFRESH-INTERVAL") == timedelta(minutes=15)

    def test_empty_calendar_still_has_a_component(self) -> None:
        calendar = parse()

        [timezone] = calendar.walk("VTIMEZONE")
        assert timezone["TZID"] == "Europe/Moscow"
        assert calendar.walk("VEVENT") == []

    def test_lines_end_with_crlf_and_fold_long_cyrillic_titles(self) -> None:
        title = "Подготовить презентацию для совещания по бюджету отдела на следующий квартал"
        content = render_calendar([card(1, EventType.TASK, at(TOMORROW, 10), title=title)], NOW)

        lines = content.split(b"\r\n")
        assert all(len(line) <= 75 for line in lines)
        assert b"\n" not in content.replace(b"\r\n", b"")
        assert str(only_event(Calendar.from_ical(content))["SUMMARY"]) == title


class TestMeeting:
    def test_start_end_and_alert_fifteen_minutes_before(self) -> None:
        meeting = card(7, EventType.MEETING, at(TOMORROW, 15), ends_at=at(TOMORROW, 16, 30))

        event = only_event(parse(meeting))

        assert event.decoded("DTSTART") == at(TOMORROW, 15)
        assert event.decoded("DTEND") == at(TOMORROW, 16, 30)
        assert event["DTSTART"].params["TZID"] == "Europe/Moscow"
        assert alarm_trigger(event) == timedelta(minutes=-15)
        assert event["TRANSP"] == "OPAQUE"
        assert str(event["UID"]) == "event-7@voice.wexasas.online"
        assert str(event["DESCRIPTION"]) == "Встреча из ассистента «Горький»."

    def test_without_end_lasts_an_hour(self) -> None:
        event = only_event(parse(card(1, EventType.MEETING, at(TOMORROW, 15))))

        assert event.decoded("DTEND") - event.decoded("DTSTART") == timedelta(hours=1)

    def test_time_from_another_offset_is_shown_in_moscow(self) -> None:
        in_utc = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

        event = only_event(parse(card(1, EventType.MEETING, in_utc)))

        assert event["DTSTART"].params["TZID"] == "Europe/Moscow"
        assert event["DTSTART"].to_ical() == b"20261027T150000"
        assert event.decoded("DTSTART") == in_utc


class TestReminderAndTimedTask:
    @pytest.mark.parametrize(
        ("event_type", "label"),
        [(EventType.REMINDER, "Напоминание"), (EventType.TASK, "Задача")],
    )
    def test_fifteen_minutes_with_alert_at_start(self, event_type: EventType, label: str) -> None:
        event = only_event(parse(card(3, event_type, at(TOMORROW, 10))))

        assert event.decoded("DTSTART") == at(TOMORROW, 10)
        assert event.decoded("DTEND") == at(TOMORROW, 10, 15)
        assert alarm_trigger(event) == timedelta(0)
        assert event["TRANSP"] == "TRANSPARENT"
        assert str(event["DESCRIPTION"]) == f"{label} из ассистента «Горький»."


class TestDateOnlyTask:
    def test_all_day_with_morning_alert(self) -> None:
        task = card(4, EventType.TASK, datetime(2026, 10, 30, tzinfo=MOSCOW), has_time=False)

        event = only_event(parse(task))

        assert event.decoded("DTSTART") == FRIDAY
        assert event.decoded("DTEND") == FRIDAY + timedelta(days=1)
        assert event["DTSTART"].params["VALUE"] == "DATE"
        assert alarm_trigger(event) == timedelta(hours=9)


class TestStamps:
    def test_service_stamps_are_utc(self) -> None:
        event = only_event(parse(card(1, EventType.TASK, at(TOMORROW, 10))))

        assert event.decoded("DTSTAMP") == NOW
        assert event["DTSTAMP"].to_ical().endswith(b"Z")
        assert event["CREATED"].to_ical().endswith(b"Z")
        assert event["LAST-MODIFIED"].to_ical().endswith(b"Z")
        assert event.decoded("LAST-MODIFIED") == NOW


def test_undated_tasks_are_skipped() -> None:
    calendar = parse(card(1, EventType.TASK, None), card(2, EventType.TASK, at(TOMORROW, 9)))

    assert [str(event["UID"]) for event in calendar.walk("VEVENT")] == [
        "event-2@voice.wexasas.online"
    ]
