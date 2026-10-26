"""`LLMIntentParser` без сети: заготовленные ответы модели → `Intent`."""

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.core.enums import EventStatus, EventType, PendingExpectation
from app.core.errors import ErrorCode
from app.core.schedule import MOSCOW
from app.llm.errors import LLMUnavailableError
from app.llm.interfaces import LLMMessage
from app.nlu.interfaces import (
    Action,
    ContextEvent,
    DialogContext,
    DialogTurn,
    Intent,
    Period,
    TargetRef,
    TimeScope,
    When,
)
from app.nlu.parser import LLMIntentParser
from app.nlu.schema import EXTRACTION_SCHEMA

NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=MOSCOW)
TOMORROW = dt.date(2026, 10, 28)
FRIDAY = dt.date(2026, 10, 30)
MEETING_WITH_IVAN = ContextEvent(
    id=401,
    type=EventType.MEETING,
    title="Встреча с Иваном",
    starts_at=dt.datetime(2026, 10, 27, 15, 0, tzinfo=MOSCOW),
)


class FakeLLM:
    """Отвечает заготовленным JSON и запоминает запрос."""

    def __init__(self, answer: Mapping[str, Any] | Exception) -> None:
        self._answer = answer
        self.messages: list[LLMMessage] = []
        self.schema: Mapping[str, Any] = {}

    async def complete_json(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.messages = list(messages)
        self.schema = json_schema
        if isinstance(self._answer, Exception):
            raise self._answer
        return dict(self._answer)


async def parse(
    answer: Mapping[str, Any], text: str = "реплика", context: DialogContext | None = None
) -> Intent:
    parser = LLMIntentParser(FakeLLM(answer))
    return await parser.parse(text, context or DialogContext(now=NOW))


async def test_reminder_with_date_and_time() -> None:
    intent = await parse(
        {
            "action": "create",
            "event_type": "reminder",
            "title": "позвонить Ивану",
            "date": "tomorrow",
            "time": "10:00",
            "day_part": "morning",
        },
        text="Напомни мне завтра в 10 утра позвонить Ивану",
    )

    assert intent == Intent(
        action=Action.CREATE,
        text="Напомни мне завтра в 10 утра позвонить Ивану",
        event_type=EventType.REMINDER,
        title="Позвонить Ивану",
        when=When(date=TOMORROW, time=dt.time(10, 0)),
    )


async def test_unnamed_time_stays_empty() -> None:
    intent = await parse(
        {
            "action": "create",
            "event_type": "meeting",
            "title": "Встреча с Иваном",
            "date": "tomorrow",
        }
    )

    assert intent.when == When(date=TOMORROW, time=None)


async def test_task_until_end_of_week() -> None:
    intent = await parse(
        {"action": "create", "event_type": "task", "title": "Купить билеты", "date": "end_of_week"}
    )

    assert intent.when == When(date=dt.date(2026, 11, 1), time=dt.time(23, 59))


async def test_task_without_date_has_no_when() -> None:
    intent = await parse({"action": "create", "event_type": "task", "title": "Купить молоко"})

    assert intent.when is None


async def test_meeting_duration_is_kept() -> None:
    intent = await parse(
        {"action": "create", "event_type": "meeting", "time": "15:00", "duration_minutes": 120}
    )

    assert intent.duration_minutes == 120


async def test_list_today_without_type() -> None:
    intent = await parse({"action": "list", "event_type": "none", "date": "today"})

    assert intent.action is Action.LIST
    assert intent.event_type is None
    assert intent.period == Period(
        start=dt.datetime(2026, 10, 27, tzinfo=MOSCOW),
        end=dt.datetime(2026, 10, 28, tzinfo=MOSCOW),
        label="сегодня",
    )


async def test_list_with_status_filter() -> None:
    intent = await parse({"action": "list", "event_type": "task", "status": "open"})

    assert intent.status is EventStatus.OPEN
    assert intent.period is None


async def test_search_keeps_query_and_time_scope() -> None:
    intent = await parse(
        {
            "action": "search",
            "event_type": "meeting",
            "query": "встреча с Иваном",
            "time_scope": "past",
        }
    )

    assert intent.query == "встреча с Иваном"
    assert intent.time_scope is TimeScope.PAST
    assert intent.event_type is EventType.MEETING


async def test_search_without_query_searches_whole_text() -> None:
    intent = await parse({"action": "search"}, text="  Найди договор с Марией ")

    assert intent.query == "Найди договор с Марией"


async def test_search_period_in_past_month() -> None:
    intent = await parse(
        {"action": "search", "query": "встреча", "date": "last_month", "time_scope": "past"}
    )

    assert intent.period is not None
    assert intent.period.start == dt.datetime(2026, 9, 1, tzinfo=MOSCOW)


async def test_reschedule_pronoun_points_to_context() -> None:
    intent = await parse({"action": "reschedule", "about_last": True, "date": "tomorrow"})

    assert intent.target == TargetRef(last=True)
    assert intent.when == When(date=TOMORROW)


async def test_reschedule_keeps_current_day_of_record_apart_from_new_time() -> None:
    intent = await parse(
        {"action": "reschedule", "query": "созвон", "target_date": "tomorrow", "time": "16:00"}
    )

    assert intent.target == TargetRef(last=False, query="созвон", when=When(date=TOMORROW))
    assert intent.when == When(time=dt.time(16, 0))


async def test_reschedule_without_description_means_record_in_context() -> None:
    intent = await parse({"action": "reschedule", "date": "fri"})

    assert intent.target is not None
    assert intent.target.last


async def test_query_with_title_of_focused_record_means_that_record() -> None:
    context = DialogContext(now=NOW, focus=(MEETING_WITH_IVAN,))

    intent = await parse(
        {"action": "reschedule", "query": "встреча с Иваном", "date": "tomorrow"}, context=context
    )

    assert intent.target is not None
    assert intent.target.last


async def test_delete_by_description_and_day() -> None:
    intent = await parse(
        {"action": "delete", "event_type": "meeting", "query": "встреча с Сергеем", "date": "thu"}
    )

    assert intent.target == TargetRef(
        last=False,
        query="встреча с Сергеем",
        event_type=EventType.MEETING,
        when=When(date=dt.date(2026, 10, 29)),
    )


async def test_complete_by_description() -> None:
    intent = await parse({"action": "complete", "query": "позвонить Ивану"})

    assert intent.action is Action.COMPLETE
    assert intent.target == TargetRef(last=False, query="позвонить Ивану")


async def test_rename_takes_new_title() -> None:
    intent = await parse(
        {"action": "rename", "query": "купить билеты", "new_title": "купить билеты в Казань"}
    )

    assert intent.title == "Купить билеты в Казань"
    assert intent.target == TargetRef(last=False, query="купить билеты")


async def test_rename_accepts_new_title_in_title_field() -> None:
    intent = await parse({"action": "rename", "about_last": True, "title": "Созвон с партнёрами"})

    assert intent.title == "Созвон с партнёрами"


async def test_answer_with_time_only() -> None:
    intent = await parse({"action": "answer", "time": "3:00"})

    assert intent == Intent(action=Action.ANSWER, text="реплика", when=When(time=dt.time(15, 0)))


async def test_answer_with_title() -> None:
    intent = await parse({"action": "answer", "title": "«созвон с отделом продаж».»"})

    assert intent.title == "Созвон с отделом продаж"


async def test_choose_number() -> None:
    intent = await parse({"action": "choose", "choice": 2})

    assert intent.choice_index == 2


async def test_choose_without_number_has_no_index() -> None:
    intent = await parse({"action": "choose", "choice": 0})

    assert intent.choice_index is None


@pytest.mark.parametrize("action", ["confirm", "deny", "undo", "smalltalk", "unknown"])
async def test_simple_actions_carry_no_fields(action: str) -> None:
    intent = await parse({"action": action, "title": "лишнее", "date": "tomorrow"})

    assert intent == Intent(action=Action(action), text="реплика")


async def test_fields_of_other_actions_are_ignored() -> None:
    intent = await parse({"action": "create", "choice": 3, "query": "лишнее", "status": "open"})

    assert intent.choice_index is None
    assert intent.query is None
    assert intent.status is None


async def test_unreadable_values_mean_not_named() -> None:
    intent = await parse(
        {
            "action": "create",
            "event_type": "birthday",
            "date": "someday",
            "time": 15,
            "duration_minutes": "долго",
        }
    )

    assert intent.event_type is None
    assert intent.when is None
    assert intent.duration_minutes is None


async def test_unknown_action_is_unknown() -> None:
    intent = await parse({"action": "fly"})

    assert intent.action is Action.UNKNOWN


async def test_parser_asks_by_schema_with_dialog_context() -> None:
    llm = FakeLLM({"action": "answer", "time": "15:00"})
    context = DialogContext(
        now=NOW,
        pending=PendingExpectation.TIME,
        pending_question="На какое время поставить встречу?",
        recent=(DialogTurn("user", "Поставь встречу с Иваном завтра"),),
        focus=(MEETING_WITH_IVAN,),
    )

    await LLMIntentParser(llm).parse("в 15:00", context)

    [system, user] = llm.messages
    assert llm.schema is EXTRACTION_SCHEMA
    assert system.role == "system"
    assert "На какое время поставить встречу?" in user.content
    assert "1. встреча «Встреча с Иваном»" in user.content
    assert user.content.endswith("Реплика пользователя: «в 15:00»")


async def test_unavailable_model_is_reported_as_llm_unavailable() -> None:
    parser = LLMIntentParser(FakeLLM(LLMUnavailableError()))

    with pytest.raises(LLMUnavailableError) as raised:
        await parser.parse("что у меня сегодня", DialogContext(now=NOW))

    assert raised.value.code is ErrorCode.LLM_UNAVAILABLE
