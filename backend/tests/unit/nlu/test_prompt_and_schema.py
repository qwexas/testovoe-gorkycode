"""Промпт и JSON-схема разбора: что видит модель."""

import datetime as dt
import json

from app.core.enums import EventType, PendingExpectation
from app.core.schedule import MOSCOW
from app.nlu.expressions import DateKind
from app.nlu.interfaces import ContextEvent, DialogContext, DialogTurn
from app.nlu.prompt import FEW_SHOT_EXAMPLES, build_messages, calendar, system_prompt
from app.nlu.schema import EXTRACTION_SCHEMA, Extraction

NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=MOSCOW)


def test_schema_describes_exactly_the_extraction_fields() -> None:
    assert list(EXTRACTION_SCHEMA["properties"]) == list(Extraction.model_fields)


def test_only_action_is_required() -> None:
    assert EXTRACTION_SCHEMA["required"] == ["action"]
    assert EXTRACTION_SCHEMA["additionalProperties"] is False


def test_record_description_comes_before_new_values() -> None:
    """GigaChat в режиме strict пишет поля по порядку схемы — см. `_PROPERTIES`."""
    order = list(EXTRACTION_SCHEMA["properties"])

    assert order.index("query") < order.index("new_title")
    assert order.index("target_date") < order.index("date")
    assert order.index("target_time") < order.index("time")
    assert order[-1] == "rest"


def test_schema_lists_every_date_kind() -> None:
    assert EXTRACTION_SCHEMA["properties"]["date"]["enum"] == [kind.value for kind in DateKind]


def test_few_shot_examples_match_the_schema() -> None:
    for _, fields in FEW_SHOT_EXAMPLES:
        assert Extraction.model_validate(fields).model_dump(include=set(fields)) == fields


def test_system_prompt_does_not_depend_on_request() -> None:
    first = build_messages("что у меня сегодня", DialogContext(now=NOW))
    second = build_messages("удали её", DialogContext(now=NOW + dt.timedelta(days=3)))

    assert first[0] == second[0]
    assert first[0].content == system_prompt()


def test_system_prompt_shows_examples_as_json() -> None:
    phrase, fields = FEW_SHOT_EXAMPLES[0]

    assert f"«{phrase}» → {json.dumps(fields, ensure_ascii=False)}" in system_prompt()


def test_user_prompt_names_current_moment() -> None:
    [_, user] = build_messages("что у меня сегодня", DialogContext(now=NOW))

    assert user.content.startswith("Сейчас: вторник, 27.10.2026, 12:00 (Москва).")


def test_calendar_spans_two_weeks_around_today() -> None:
    lines = calendar(NOW.date()).splitlines()

    assert len(lines) == 5
    assert lines[0].startswith("позапрошлая неделя: пн 12.10")
    assert "вт 27.10 (сегодня)" in lines[2]
    assert lines[4].endswith("вс 15.11")


def test_pending_question_comes_right_before_the_reply() -> None:
    context = DialogContext(
        now=NOW,
        pending=PendingExpectation.CHOICE,
        pending_question="Какую перенести?",
        recent=(DialogTurn("user", "Перенеси встречу"), DialogTurn("assistant", "Какую?")),
    )

    [_, user] = build_messages("вторую", context)

    *_, pending_line, reply_line = user.content.splitlines()
    assert pending_line.startswith("Ассистент ждёт: выбор одного из вариантов — вопрос «Какую")
    assert reply_line == "Реплика пользователя: «вторую»"
    assert "пользователь: Перенеси встречу\nассистент: Какую?" in user.content


def test_focus_records_are_numbered_from_one() -> None:
    context = DialogContext(
        now=NOW,
        focus=(
            ContextEvent(1, EventType.MEETING, "Встреча с Ольгой", dt.datetime(2026, 10, 29, 14)),
            ContextEvent(2, EventType.TASK, "Купить билеты", None),
        ),
    )

    [_, user] = build_messages("вторую", context)

    assert "1. встреча «Встреча с Ольгой», чт 29.10 14:00" in user.content
    assert "2. задача «Купить билеты», без срока" in user.content


def test_no_dialog_sections_without_context() -> None:
    [_, user] = build_messages("привет", DialogContext(now=NOW))

    assert "Ассистент ждёт" not in user.content
    assert "Записи в фокусе" not in user.content
