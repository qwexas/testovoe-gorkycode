"""Шаблоны ответов: даты по-человечески, числа и падежи, сводки."""

from datetime import date, datetime

import pytest

from app.core.dialog import phrases
from app.core.enums import EventType, PendingExpectation
from app.nlu.interfaces import Action
from tests.unit.dialog.support import TODAY, at, card

FIRST_SYMBOL_CODE_POINT = 0x2600


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "дело"),
        (2, "дела"),
        (4, "дела"),
        (5, "дел"),
        (11, "дел"),
        (14, "дел"),
        (21, "дело"),
        (22, "дела"),
        (0, "дел"),
    ],
)
def test_plural(count: int, expected: str) -> None:
    assert phrases.plural(count, phrases.THING.counted) == expected


@pytest.mark.parametrize(
    ("count", "noun", "expected"),
    [
        (1, phrases.THING, "одно дело"),
        (1, phrases.TYPE_NOUNS[EventType.MEETING], "одна встреча"),
        (1, phrases.TYPE_NOUNS[EventType.REMINDER], "одно напоминание"),
        (3, phrases.ENTRY, "3 записи"),
        (12, phrases.TYPE_NOUNS[EventType.TASK], "12 задач"),
    ],
)
def test_count_phrase(count: int, noun: phrases.Noun, expected: str) -> None:
    assert phrases.count_phrase(count, noun) == expected


@pytest.mark.parametrize(
    ("moment", "has_time", "expected"),
    [
        (at(TODAY, 15), True, "сегодня, 26 октября, в 15:00"),
        (at(date(2026, 10, 27), 9, 30), True, "завтра, 27 октября, в 9:30"),
        (at(date(2026, 10, 28), 0), False, "послезавтра, 28 октября"),
        (at(date(2026, 10, 25), 18), True, "вчера, 25 октября, в 18:00"),
        (at(date(2026, 10, 27), 0), True, "завтра, 27 октября, в 0:00"),
        (at(date(2026, 10, 30), 0), False, "в пятницу, 30 октября"),
        (at(date(2026, 11, 1), 23, 59), True, "в воскресенье, 1 ноября, в 23:59"),
        (at(date(2026, 11, 3), 10), True, "3 ноября в 10:00"),
        (at(date(2026, 3, 5), 15, 45), True, "5 марта 2026 в 15:45"),
        (at(date(2027, 1, 10), 0), False, "10 января 2027"),
    ],
)
def test_when_text(moment: datetime, has_time: bool, expected: str) -> None:
    assert phrases.when_text(moment, has_time, TODAY) == expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (at(date(2026, 10, 27), 15), "на завтра, 27 октября, в 15:00"),
        (at(date(2026, 10, 29), 16), "на четверг, 29 октября, в 16:00"),
        (at(date(2026, 12, 1), 9), "на 1 декабря в 9:00"),
    ],
)
def test_onto_text(moment: datetime, expected: str) -> None:
    assert phrases.onto_text(moment, True, TODAY) == expected


def test_tuesday_uses_vo() -> None:
    assert phrases.when_text(at(date(2026, 11, 3), 0), False, date(2026, 10, 30)) == (
        "во вторник, 3 ноября"
    )


@pytest.mark.parametrize(
    ("week_of", "expected"),
    [
        (date(2026, 10, 26), "этой недели"),
        (date(2026, 11, 2), "следующей недели"),
        (date(2026, 11, 9), "недели с 9 ноября"),
    ],
)
def test_week_text(week_of: date, expected: str) -> None:
    assert phrases.week_text(week_of, TODAY) == expected


def test_schedule_of_undated_task() -> None:
    assert phrases.schedule_text(card(EventType.TASK, "Купить хлеб", None), TODAY) == "без срока"


def test_created_meeting_with_custom_duration() -> None:
    meeting = card(
        EventType.MEETING,
        "Демо",
        at(date(2026, 10, 27), 15),
        ends_at=at(date(2026, 10, 27), 16, 30),
    )

    assert (
        phrases.created(meeting, TODAY) == "Встреча «Демо» — завтра, 27 октября, с 15:00 до 16:30."
    )


@pytest.mark.parametrize(
    ("action", "event_type", "expected"),
    [
        (Action.RESCHEDULE, EventType.MEETING, "Какую встречу перенести?"),
        (Action.RENAME, EventType.TASK, "Какую задачу переименовать?"),
        (Action.COMPLETE, EventType.TASK, "Какую задачу отметить сделанной?"),
        (Action.COMPLETE, EventType.REMINDER, "Какое напоминание отметить сделанным?"),
        (Action.DELETE, EventType.REMINDER, "Какое напоминание удалить?"),
    ],
)
def test_choice_question(action: Action, event_type: EventType, expected: str) -> None:
    assert phrases.choice_question(action, phrases.TYPE_NOUNS[event_type]) == expected


@pytest.mark.parametrize(
    ("expects", "action", "expected"),
    [
        (PendingExpectation.CONFIRM, Action.DELETE, "Хорошо, не удаляю."),
        (PendingExpectation.CONFIRM, Action.CREATE, "Хорошо, не добавляю."),
        (PendingExpectation.CONFIRM, Action.RESCHEDULE, "Хорошо, оставляю как было."),
        (PendingExpectation.TIME, Action.CREATE, "Хорошо, не добавляю."),
        (PendingExpectation.CHOICE, Action.RENAME, "Хорошо, ничего не меняю."),
    ],
)
def test_declined(expects: PendingExpectation, action: Action, expected: str) -> None:
    assert phrases.declined(expects, action) == expected


def test_replies_have_no_emoji() -> None:
    """Дизайнер просил без эмодзи: все символы шаблонов — до блока Miscellaneous Symbols."""
    texts = [value for value in vars(phrases).values() if isinstance(value, str)]

    assert all(ord(char) < FIRST_SYMBOL_CODE_POINT for text in texts for char in text)
