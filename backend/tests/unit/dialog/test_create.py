"""Создание записей (Q30), слияние ответа с отложенным разбором и конфликт встреч."""

from datetime import date, time, timedelta
from typing import Any

import pytest

from app.core.dialog.phrases import EN_DASH
from app.core.enums import EventStatus, EventType, PendingExpectation, ReplyKind
from app.nlu.interfaces import Action, Intent, When
from tests.unit.dialog.support import (
    NEXT_MONDAY,
    THURSDAY,
    TODAY,
    TOMORROW,
    DialogHarness,
    answer,
    at,
    change,
    create,
    it,
    listing,
    simple,
)

DAY_AFTER_TOMORROW = TOMORROW + timedelta(days=1)


async def ask(
    dialog: DialogHarness,
    text: str,
    event_type: EventType | None,
    title: str | None,
    **fields: Any,
) -> str:
    """Реплика-команда создания; возвращает уточняющий вопрос ассистента."""
    reply = await dialog.say(create(text, event_type, title, **fields))
    assert reply.kind is ReplyKind.CLARIFICATION, reply.text
    assert reply.pending is not None
    return reply.text


class TestTask:
    async def test_without_date_is_saved_without_due(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(create("Купить молоко", EventType.TASK, "купить молоко"))

        assert reply.text == "Задача «Купить молоко» — без срока."
        [event] = reply.events
        assert (event.starts_at, event.has_time) == (None, False)

    async def test_week_of_means_sunday_deadline(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Сделать ремонт на следующей неделе",
                EventType.TASK,
                "Сделать ремонт",
                week_of=NEXT_MONDAY,
            )
        )

        assert reply.events[0].starts_at == at(date(2026, 11, 8), 23, 59)

    async def test_unknown_type_is_task(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(create("Завтра купить хлеб", None, "Купить хлеб", date=TOMORROW))

        assert reply.events[0].type is EventType.TASK

    async def test_time_without_date_is_nearest(self, dialog: DialogHarness) -> None:
        later_today = await dialog.say(
            create("В 18 полить цветы", EventType.TASK, "Полить цветы", time=time(18, 0))
        )
        passed_today = await dialog.say(
            create("В 9 сделать зарядку", EventType.TASK, "Сделать зарядку", time=time(9, 0))
        )

        assert later_today.events[0].starts_at == at(TODAY, 18)
        assert passed_today.events[0].starts_at == at(TOMORROW, 9)

    async def test_missing_title_is_asked(self, dialog: DialogHarness) -> None:
        question = await ask(dialog, "Поставь задачу", EventType.TASK, None)
        reply = await dialog.say(answer("купить подарок маме"))

        assert question == "Как назвать задачу?"
        assert reply.text == "Задача «Купить подарок маме» — без срока."


class TestReminder:
    async def test_nothing_known_asks_when(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog, "Напомни позвонить маме", EventType.REMINDER, "Позвонить маме"
        ) == ("Когда напомнить?")
        assert dialog.state is not None and dialog.state.pending is not None
        assert dialog.state.pending["question"]["expects"] == PendingExpectation.DATETIME

    async def test_date_without_time_asks_time(self, dialog: DialogHarness) -> None:
        question = await ask(
            dialog,
            "Напомни завтра позвонить маме",
            EventType.REMINDER,
            "Позвонить маме",
            date=TOMORROW,
        )

        assert question == "Во сколько напомнить?"

    async def test_time_only_is_nearest_occurrence(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Напомни в 18 выключить духовку",
                EventType.REMINDER,
                "Выключить духовку",
                time=time(18, 0),
            )
        )

        assert reply.text == "Напоминание «Выключить духовку» — сегодня, 26 октября, в 18:00."

    async def test_week_only_asks_day(self, dialog: DialogHarness) -> None:
        question = await ask(
            dialog,
            "Напомни на следующей неделе",
            EventType.REMINDER,
            "Оплатить счёт",
            week_of=NEXT_MONDAY,
        )

        assert question == "В какой день следующей недели напомнить?"

    async def test_missing_content_is_asked(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog, "Напомни завтра в 9", EventType.REMINDER, None, date=TOMORROW, time=time(9)
        ) == ("О чём напомнить?")

    async def test_two_answers_complete_reminder(self, dialog: DialogHarness) -> None:
        await ask(dialog, "Напомни позвонить маме", EventType.REMINDER, "Позвонить маме")
        second = await dialog.say(answer("завтра", date=TOMORROW))
        done = await dialog.say(answer("в 9 утра", time=time(9, 0)))

        assert second.text == "Во сколько напомнить?"
        assert done.text == "Напоминание «Позвонить маме» — завтра, 27 октября, в 9:00."


class TestMeeting:
    async def test_without_time(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog, "Встреча с Иваном завтра", EventType.MEETING, "Встреча с Иваном", date=TOMORROW
        ) == ("На какое время поставить встречу?")

    async def test_without_date(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog, "Встреча с Иваном в 15", EventType.MEETING, "Встреча с Иваном", time=time(15)
        ) == ("На какой день поставить встречу?")

    async def test_without_date_and_time(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog, "Поставь встречу с Иваном", EventType.MEETING, "Встреча с Иваном"
        ) == ("На какой день и время поставить встречу?")

    async def test_next_week_asks_day_of_that_week(self, dialog: DialogHarness) -> None:
        assert (
            await ask(
                dialog,
                "Встреча с Иваном на следующей неделе в 15",
                EventType.MEETING,
                "Встреча с Иваном",
                week_of=NEXT_MONDAY,
                time=time(15),
            )
            == "На какой день следующей недели?"
        )

        reply = await dialog.say(answer("в среду", date=date(2026, 11, 4)))

        assert reply.events[0].starts_at == at(date(2026, 11, 4), 15)

    async def test_missing_title(self, dialog: DialogHarness) -> None:
        assert await ask(
            dialog,
            "Поставь встречу завтра в 15",
            EventType.MEETING,
            None,
            date=TOMORROW,
            time=time(15),
        ) == ("Как назвать встречу?")
        reply = await dialog.say(answer("Созвон с отделом продаж", title="Созвон с отделом продаж"))

        assert reply.text == "Встреча «Созвон с отделом продаж» — завтра, 27 октября, в 15:00."

    async def test_default_duration_is_hour(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Встреча завтра в 15", EventType.MEETING, "Планёрка", date=TOMORROW, time=time(15)
            )
        )

        assert reply.events[0].ends_at == at(TOMORROW, 16)

    async def test_named_duration(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Встреча завтра с 15 до 16:30",
                EventType.MEETING,
                "Планёрка",
                date=TOMORROW,
                time=time(15),
                duration_minutes=90,
            )
        )

        assert reply.events[0].ends_at == at(TOMORROW, 16, 30)
        assert reply.text == "Встреча «Планёрка» — завтра, 27 октября, с 15:00 до 16:30."


class TestPendingAnswer:
    async def test_answer_without_pending_is_not_understood(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(answer("в 15", time=time(15)))

        assert reply.kind is ReplyKind.INFO
        assert reply.text.startswith("Не понял, что сделать.")

    async def test_new_command_drops_pending(self, dialog: DialogHarness) -> None:
        await ask(
            dialog,
            "Поставь встречу с Иваном завтра",
            EventType.MEETING,
            "Встреча с Иваном",
            date=TOMORROW,
        )

        reply = await dialog.say(listing("Что у меня сегодня?"))
        after = await dialog.say(answer("в 15", time=time(15)))

        assert reply.kind is ReplyKind.LIST
        assert after.kind is ReplyKind.INFO
        assert not [
            e for e in dialog.storage.events.records.values() if e.title == "Встреча с Иваном"
        ]

    async def test_deny_cancels_creation(self, dialog: DialogHarness) -> None:
        await ask(
            dialog,
            "Поставь встречу с Иваном завтра",
            EventType.MEETING,
            "Встреча с Иваном",
            date=TOMORROW,
        )

        reply = await dialog.say(simple(Action.DENY, "не надо"))

        assert reply.text == "Хорошо, не добавляю."
        assert dialog.state is not None and dialog.state.pending is None

    async def test_confirm_instead_of_time_repeats_question(self, dialog: DialogHarness) -> None:
        await ask(
            dialog,
            "Поставь встречу с Иваном завтра",
            EventType.MEETING,
            "Встреча с Иваном",
            date=TOMORROW,
        )

        reply = await dialog.say(simple(Action.CONFIRM, "да"))

        assert reply.kind is ReplyKind.CLARIFICATION
        assert reply.text == "На какое время поставить встречу?"
        assert dialog.state is not None and dialog.state.pending is not None


class TestConflicts:
    @pytest.fixture
    async def standup(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 15))

    async def ask_overlap(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Встреча с Иваном завтра в 15:30",
                EventType.MEETING,
                "Встреча с Иваном",
                date=TOMORROW,
                time=time(15, 30),
            )
        )
        assert reply.kind is ReplyKind.CONFIRM_REQUEST
        assert reply.text == (
            f"В это время уже стоит «Планёрка» (15:00{EN_DASH}16:00). Всё равно добавить?"
        )
        assert [card.title for card in reply.conflicts] == ["Планёрка"]
        assert reply.pending is not None and reply.pending.expects is PendingExpectation.CONFIRM
        assert reply.events == ()

    async def test_confirm_creates(self, dialog: DialogHarness, standup: None) -> None:
        await self.ask_overlap(dialog)

        reply = await dialog.say(simple(Action.CONFIRM, "да, всё равно добавь"))

        assert reply.kind is ReplyKind.CONFIRMATION
        assert reply.events[0].starts_at == at(TOMORROW, 15, 30)

    async def test_deny_does_not_create(self, dialog: DialogHarness, standup: None) -> None:
        await self.ask_overlap(dialog)

        reply = await dialog.say(simple(Action.DENY, "нет"))

        assert reply.text == "Хорошо, не добавляю."
        assert len(dialog.storage.events.records) == 1

    async def test_other_time_in_answer_rechecks(
        self, dialog: DialogHarness, standup: None
    ) -> None:
        await self.ask_overlap(dialog)

        reply = await dialog.say(answer("давай в 17", time=time(17)))

        assert reply.text == "Встреча «Встреча с Иваном» — завтра, 27 октября, в 17:00."

    async def test_move_it_during_conflict_moves_the_new_meeting(
        self, dialog: DialogHarness, standup: None
    ) -> None:
        await self.ask_overlap(dialog)

        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "А перенеси её на послезавтра",
                target=it(),
                when=When(date=DAY_AFTER_TOMORROW),
            )
        )

        assert reply.text == "Встреча «Встреча с Иваном» — послезавтра, 28 октября, в 15:30."
        standup_record = next(
            e for e in dialog.storage.events.records.values() if e.title == "Планёрка"
        )
        assert standup_record.starts_at == at(TOMORROW, 15)

    async def test_touching_meetings_do_not_conflict(
        self, dialog: DialogHarness, standup: None
    ) -> None:
        reply = await dialog.say(
            create("Встреча в 16", EventType.MEETING, "Разбор", date=TOMORROW, time=time(16))
        )

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_done_meeting_and_tasks_do_not_conflict(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.MEETING, "Старая встреча", at(THURSDAY, 15), status=EventStatus.DONE
        )
        await dialog.add_event(EventType.TASK, "Задача в это время", at(THURSDAY, 15))

        reply = await dialog.say(
            create(
                "Встреча в четверг в 15", EventType.MEETING, "Разбор", date=THURSDAY, time=time(15)
            )
        )

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_several_conflicts_are_listed(self, dialog: DialogHarness, standup: None) -> None:
        await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 15, 30))

        reply = await dialog.say(
            create(
                "Встреча завтра в 15:15",
                EventType.MEETING,
                "Разбор",
                date=TOMORROW,
                time=time(15, 15),
            )
        )

        assert reply.text == (
            f"В это время уже стоят «Планёрка» (15:00{EN_DASH}16:00) "
            f"и «Созвон» (15:30{EN_DASH}16:30). "
            "Всё равно добавить?"
        )


class TestDuplicates:
    """Повтор той же записи (тип, название, время) — переспросить, а не создать молча."""

    def call_ivan(self, text: str = "Напомни завтра в 10 позвонить Ивану", **fields: Any) -> Intent:
        values: dict[str, Any] = {"date": TOMORROW, "time": time(10)} | fields
        title = values.pop("title", "Позвонить Ивану")
        event_type = values.pop("event_type", EventType.REMINDER)
        return create(text, event_type, title, **values)

    async def test_same_reminder_asks(self, dialog: DialogHarness) -> None:
        first = await dialog.say(self.call_ivan())

        reply = await dialog.say(self.call_ivan("Напомни завтра в 10 позвонить Ивану ещё раз"))

        assert reply.kind is ReplyKind.CONFIRM_REQUEST
        assert reply.text == (
            "Такое напоминание уже есть: «Позвонить Ивану» — завтра в 10:00. Добавить ещё одно?"
        )
        assert [card.id for card in reply.events] == [first.events[0].id]
        assert reply.pending is not None and reply.pending.expects is PendingExpectation.CONFIRM
        assert len(dialog.storage.events.records) == 1

    async def test_confirm_adds_another(self, dialog: DialogHarness) -> None:
        await dialog.say(self.call_ivan())
        await dialog.say(self.call_ivan("Ещё раз: напомни завтра в 10 позвонить Ивану"))

        reply = await dialog.say(simple(Action.CONFIRM, "да, добавь"))

        assert reply.kind is ReplyKind.CONFIRMATION
        assert len(dialog.storage.events.records) == 2

    async def test_deny_does_not_add(self, dialog: DialogHarness) -> None:
        await dialog.say(self.call_ivan())
        await dialog.say(self.call_ivan("Ещё раз: напомни завтра в 10 позвонить Ивану"))

        reply = await dialog.say(simple(Action.DENY, "нет"))

        assert reply.text == "Хорошо, не добавляю."
        assert len(dialog.storage.events.records) == 1

    async def test_title_is_compared_normalized(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.REMINDER, "Позвонить Ивану", at(TOMORROW, 10))

        reply = await dialog.say(self.call_ivan(title="позвонить  ивану!"))

        assert reply.kind is ReplyKind.CONFIRM_REQUEST

    @pytest.mark.parametrize(
        "changed",
        [
            {"time": time(11)},
            {"date": THURSDAY},
            {"title": "Позвонить Ольге"},
            {"event_type": EventType.TASK},
        ],
    )
    async def test_different_record_is_created_without_question(
        self, dialog: DialogHarness, changed: dict[str, Any]
    ) -> None:
        await dialog.add_event(EventType.REMINDER, "Позвонить Ивану", at(TOMORROW, 10))

        reply = await dialog.say(self.call_ivan(**changed))

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_done_record_is_not_a_duplicate(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.REMINDER, "Позвонить Ивану", at(TOMORROW, 10), status=EventStatus.DONE
        )

        reply = await dialog.say(self.call_ivan())

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_undated_task(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Купить хлеб")

        reply = await dialog.say(create("Купить хлеб", EventType.TASK, "купить хлеб"))

        assert reply.text == "Такая задача уже есть: «Купить хлеб» — без срока. Добавить ещё одну?"

    async def test_duplicate_meeting_is_asked_once(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 15))

        asked = await dialog.say(
            create(
                "Планёрка завтра в 15", EventType.MEETING, "Планёрка", date=TOMORROW, time=time(15)
            )
        )
        created = await dialog.say(simple(Action.CONFIRM, "да"))

        assert asked.text.startswith("Такая встреча уже есть: «Планёрка» — завтра в 15:00.")
        assert created.kind is ReplyKind.CONFIRMATION
