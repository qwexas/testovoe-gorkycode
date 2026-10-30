"""F01/F02: явные ограничения нельзя заменять другой записью или фокусом."""

from datetime import time
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.enums import EventStatus, EventType, MessageSource, ReplyKind
from app.nlu.intent_builder import build_intent
from app.nlu.interfaces import Action, ContextEvent, DialogContext, TargetRef, When
from app.nlu.parser import LLMIntentParser
from app.nlu.schema import Extraction
from tests.unit.dialog.support import (
    NOW,
    TODAY,
    TOMORROW,
    at,
    change,
    create,
    listing,
    new_dialog,
)


@pytest.mark.parametrize(
    "action", [Action.COMPLETE, Action.RESCHEDULE, Action.DELETE, Action.RENAME]
)
async def test_missing_exact_time_does_not_change_another_record(action: Action) -> None:
    dialog = new_dialog()
    card = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 14))

    reply = await dialog.say(
        change(
            action,
            "Изменить созвон в 15:00",
            target=TargetRef(query="созвон", when=When(date=TOMORROW, time=time(15))),
            when=When(date=TOMORROW, time=time(17)),
            title="Новое название",
        )
    )

    assert reply.kind is ReplyKind.INFO
    assert not reply.events and reply.undo is None
    assert dialog.event(card.id).starts_at == at(TOMORROW, 14)
    assert dialog.event(card.id).status is EventStatus.OPEN
    assert dialog.event(card.id).title == "Созвон"
    assert dialog.state.pending is None


async def test_explicit_type_filters_search_even_if_wrong_type_scores_higher() -> None:
    dialog = new_dialog()
    wrong = await dialog.add_event(EventType.TASK, "Созвон", at(TOMORROW, 15))
    right = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 15))
    dialog.ranker.score_shifts[wrong.id] = 1.0

    reply = await dialog.say(
        change(
            Action.COMPLETE,
            "Отметь созвон",
            target=TargetRef(
                query="созвон",
                event_type=EventType.MEETING,
            ),
        )
    )

    assert reply.events[0].id == right.id
    assert dialog.event(wrong.id).status is EventStatus.OPEN


@pytest.mark.parametrize(
    "target",
    [
        TargetRef(last=True, event_type=EventType.MEETING),
        TargetRef(last=True, when=When(date=TOMORROW)),
        TargetRef(last=True, when=When(time=time(15))),
    ],
)
async def test_focus_cannot_bypass_explicit_constraints(target: TargetRef) -> None:
    dialog = new_dialog()
    card = await dialog.add_event(EventType.TASK, "Отчёт", at(TODAY, 14))
    await dialog.say(listing("Что сегодня?"))

    reply = await dialog.say(change(Action.COMPLETE, "Отметь её", target=target))

    assert reply.kind is ReplyKind.INFO and not reply.events
    assert dialog.event(card.id).status is EventStatus.OPEN


async def test_constraints_filter_list_before_asking_for_choice() -> None:
    dialog = new_dialog()
    wrong = await dialog.add_event(EventType.MEETING, "Созвон", at(TODAY, 14))
    right = await dialog.add_event(EventType.MEETING, "Созвон", at(TODAY, 15))
    await dialog.say(listing("Что сегодня?"))

    reply = await dialog.say(
        change(
            Action.COMPLETE,
            "Отметь эту встречу в 15:00",
            target=TargetRef(
                last=True,
                event_type=EventType.MEETING,
                when=When(time=time(15)),
            ),
        )
    )

    assert reply.events[0].id == right.id
    assert dialog.event(wrong.id).status is EventStatus.OPEN


async def test_open_wrong_time_does_not_hide_completed_exact_match() -> None:
    dialog = new_dialog()
    wrong = await dialog.add_event(EventType.TASK, "Отчёт", at(TODAY, 14))
    right = await dialog.add_event(EventType.TASK, "Отчёт", at(TODAY, 15), status=EventStatus.DONE)

    reply = await dialog.say(
        change(
            Action.COMPLETE,
            "Отметь отчёт в 15:00",
            target=TargetRef(
                query="отчёт",
                when=When(date=TODAY, time=time(15)),
            ),
        )
    )

    assert reply.events[0].id == right.id
    assert dialog.event(wrong.id).status is EventStatus.OPEN


async def test_named_repeat_in_another_day_wins_over_focus() -> None:
    dialog = new_dialog()
    focused = await dialog.add_event(EventType.MEETING, "Созвон", at(TODAY, 15))
    right = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 15))
    await dialog.say(listing("Что сегодня?"))
    context = DialogContext(
        now=NOW,
        focus=(
            ContextEvent(
                id=focused.id,
                type=focused.type,
                title=focused.title,
                starts_at=focused.starts_at,
            ),
        ),
    )
    intent = build_intent(
        Extraction.model_validate(
            {
                "action": "complete",
                "event_type": "meeting",
                "query": "созвон",
                "date": "tomorrow",
            }
        ),
        "Отметь завтрашний созвон",
        context,
    )

    reply = await dialog.say(intent)

    assert reply.events[0].id == right.id
    assert dialog.event(focused.id).status is EventStatus.OPEN


async def test_task_constraint_still_includes_reminders() -> None:
    dialog = new_dialog()
    reminder = await dialog.add_event(EventType.REMINDER, "Отчёт", at(TODAY, 15))

    reply = await dialog.say(
        change(
            Action.COMPLETE,
            "Отметь задачу отчёт",
            target=TargetRef(
                query="отчёт",
                event_type=EventType.TASK,
            ),
        )
    )

    assert reply.events[0].id == reminder.id


@pytest.mark.parametrize("reference", ["последнюю", "последний"])
async def test_last_reference_completes_last_created_task(
    reference: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = new_dialog()
    first = await dialog.say(create("Создай купить молоко", EventType.TASK, "Купить молоко"))
    last = await dialog.say(create("Создай купить хлеб", EventType.TASK, "Купить хлеб"))
    llm = Mock()
    llm.complete_json = AsyncMock(return_value={"action": "complete", "about_last": True})
    monkeypatch.setattr(dialog.parser, "parse", LLMIntentParser(llm).parse)

    answer = await dialog.service.handle(
        dialog.profile_id,
        f"Отметь {reference} выполненной",
        MessageSource.TEXT,
    )

    assert answer.reply.events[0].id == last.events[0].id
    assert dialog.event(last.events[0].id).status is EventStatus.DONE
    assert dialog.event(first.events[0].id).status is EventStatus.OPEN


async def test_incorrect_about_last_does_not_replace_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = new_dialog()
    report = await dialog.say(
        create(
            "Создай проверить последний отчёт",
            EventType.TASK,
            "Проверить последний отчёт",
        )
    )
    bread = await dialog.say(create("Создай купить хлеб", EventType.TASK, "Купить хлеб"))
    llm = Mock()
    llm.complete_json = AsyncMock(
        return_value={
            "action": "complete",
            "about_last": True,
            "query": "Проверить последний отчёт",
        }
    )
    monkeypatch.setattr(dialog.parser, "parse", LLMIntentParser(llm).parse)

    answer = await dialog.service.handle(
        dialog.profile_id,
        "Отметь задачу проверить последний отчёт",
        MessageSource.TEXT,
    )

    assert answer.reply.events[0].id == report.events[0].id
    assert dialog.event(report.events[0].id).status is EventStatus.DONE
    assert dialog.event(bread.events[0].id).status is EventStatus.OPEN


@pytest.mark.parametrize("about_last", [True, False])
@pytest.mark.parametrize(
    ("action", "text", "fields"),
    [
        ("complete", "Отметь эту задачу Купить хлеб выполненной", {}),
        ("delete", "Удали эту задачу Купить хлеб", {}),
        ("reschedule", "Перенеси эту задачу Купить хлеб на завтра", {"date": "tomorrow"}),
        (
            "rename",
            "Переименуй эту задачу Купить хлеб в Купить булочки",
            {"new_title": "Купить булочки"},
        ),
    ],
)
async def test_explicit_description_after_demonstrative_changes_only_named_task(
    action: str,
    text: str,
    fields: dict[str, str],
    about_last: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R01: исходная фраза → ответ модели → Intent → действие при другом focus."""
    dialog = new_dialog()
    bread = await dialog.say(create("Создай купить хлеб", EventType.TASK, "Купить хлеб"))
    milk = await dialog.say(create("Создай купить молоко", EventType.TASK, "Купить молоко"))
    bread_id, milk_id = bread.events[0].id, milk.events[0].id
    llm = Mock(
        complete_json=AsyncMock(
            return_value={
                "action": action,
                "event_type": "task",
                "query": "Купить хлеб",
                "about_last": about_last,
                **fields,
            }
        )
    )
    monkeypatch.setattr(dialog.parser, "parse", LLMIntentParser(llm).parse)

    answer = await dialog.service.handle(dialog.profile_id, text, MessageSource.TEXT)

    assert answer.reply.events[0].id == bread_id
    if action == "delete":
        assert answer.reply.kind is ReplyKind.CONFIRM_REQUEST
        llm.complete_json.return_value = {"action": "confirm"}
        answer = await dialog.service.handle(dialog.profile_id, "Да", MessageSource.TEXT)
        assert answer.reply.kind is ReplyKind.CONFIRMATION
        assert dialog.event(bread_id) is None
    elif action == "complete":
        assert dialog.event(bread_id).status is EventStatus.DONE
    elif action == "rename":
        assert dialog.event(bread_id).title == "Купить булочки"
    else:
        assert dialog.event(bread_id).starts_at == at(TOMORROW, 0)
    assert dialog.event(milk_id).title == "Купить молоко"
    assert dialog.event(milk_id).status is EventStatus.OPEN
    assert dialog.event(milk_id).starts_at is None


@pytest.mark.parametrize("matches", [0, 2])
async def test_description_after_demonstrative_does_not_fall_back_to_focus(
    matches: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = new_dialog()
    candidates = [
        await dialog.add_event(EventType.TASK, "Купить хлеб", at(day, 9))
        for day in (TODAY, TOMORROW)[:matches]
    ]
    milk = await dialog.say(create("Создай купить молоко", EventType.TASK, "Купить молоко"))
    llm = Mock(
        complete_json=AsyncMock(
            return_value={"action": "complete", "event_type": "task", "query": "Купить хлеб"}
        )
    )
    monkeypatch.setattr(dialog.parser, "parse", LLMIntentParser(llm).parse)

    answer = await dialog.service.handle(
        dialog.profile_id, "Отметь эту задачу Купить хлеб выполненной", MessageSource.TEXT
    )

    assert answer.reply.kind is (ReplyKind.CHOICE if matches else ReplyKind.INFO)
    assert answer.reply.undo is None
    assert {card.id for card in answer.reply.choices} == {card.id for card in candidates}
    assert all(dialog.event(card.id).status is EventStatus.OPEN for card in candidates)
    assert dialog.event(milk.events[0].id).status is EventStatus.OPEN
