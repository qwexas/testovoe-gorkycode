"""Изменение записей голосом: цель из контекста или поиском, выбор, перенос, удаление."""

from datetime import date, time, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.core.enums import EventStatus, EventType, PendingExpectation, ReplyKind
from app.nlu.interfaces import Action, Intent, TargetRef, TimeScope, When
from tests.unit.dialog.support import (
    FRIDAY,
    NEXT_MONDAY,
    THURSDAY,
    TODAY,
    TOMORROW,
    DialogHarness,
    about,
    answer,
    at,
    change,
    choose,
    create,
    it,
    listing,
    simple,
)


def move(text: str, target: TargetRef, **when: Any) -> Intent:
    """RESCHEDULE: `when` — новое время записи."""
    return change(Action.RESCHEDULE, text, target=target, when=When(**when))


class TestTarget:
    async def test_it_refers_to_last_created(self, dialog: DialogHarness) -> None:
        await dialog.say(
            create(
                "Встреча с Ольгой завтра в 10",
                EventType.MEETING,
                "Встреча с Ольгой",
                date=TOMORROW,
                time=time(10),
            )
        )

        reply = await dialog.say(change(Action.COMPLETE, "Отметь её", target=it()))

        assert reply.text == "Отметил как сделанное: «Встреча с Ольгой»."

    async def test_it_without_context(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(change(Action.DELETE, "Удали её", target=it()))

        assert reply.kind is ReplyKind.INFO
        assert reply.text.startswith("Не понял, о какой записи речь.")

    async def test_named_type_picks_matching_focus(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(EventType.MEETING, "Демо", at(TODAY, 15))
        await dialog.add_event(EventType.TASK, "Отчёт", at(TODAY, 18))
        await dialog.say(listing("Что у меня сегодня?"))

        reply = await dialog.say(
            change(
                Action.COMPLETE,
                "Отметь встречу",
                target=TargetRef(last=True, event_type=EventType.MEETING),
            )
        )

        assert reply.events[0].id == meeting.id

    async def test_query_not_found(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            change(Action.DELETE, "Удали встречу с Петром", target=about("встреча с Петром"))
        )

        assert (
            reply.text
            == "Не нашёл ничего похожего на «встреча с Петром». Попробуйте сказать иначе."
        )

    async def test_single_match_is_changed_at_once(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.TASK, "Отправить отчёт Ольге", at(FRIDAY, 0), has_time=False
        )

        reply = await dialog.say(
            change(
                Action.RENAME,
                "Переименуй задачу про отчёт в «Отправить отчёт Ивану»",
                target=about("отчёт"),
                title="Отправить отчёт Ивану",
            )
        )

        assert (
            reply.text
            == "Переименовал: «Отправить отчёт Ольге» теперь называется «Отправить отчёт Ивану»."
        )
        assert reply.undo is not None

    async def test_day_of_target_narrows_search(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Созвон с Пульсом", at(TOMORROW, 10))
        thursday = await dialog.add_event(EventType.MEETING, "Созвон с Пульсом", at(THURSDAY, 10))

        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси созвон с Пульсом в четверг на 12",
                target=about("созвон Пульс", when=When(date=THURSDAY)),
                when=When(time=time(12)),
            )
        )

        assert reply.events[0].id == thursday.id
        assert reply.events[0].starts_at == at(THURSDAY, 12)

    async def test_time_of_target_prefers_exact_match(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 10))
        at_three = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 15))

        reply = await dialog.say(
            change(
                Action.DELETE,
                "Удали завтрашний созвон в 15",
                target=about("созвон", when=When(date=TOMORROW, time=time(15))),
            )
        )

        assert reply.events[0].id == at_three.id

    async def test_complete_searches_open_first(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.TASK, "Позвонить Ивану", at(date(2025, 5, 1), 10), status=EventStatus.DONE
        )
        open_call = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(TOMORROW, 10))

        reply = await dialog.say(
            change(Action.COMPLETE, "Отметь звонок Ивану", target=about("позвонить Ивану"))
        )

        assert reply.events[0].id == open_call.id

    async def test_complete_falls_back_to_done(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.TASK, "Позвонить Ивану", at(date(2025, 5, 1), 10), status=EventStatus.DONE
        )

        reply = await dialog.say(
            change(Action.COMPLETE, "Отметь звонок Ивану", target=about("позвонить Ивану"))
        )

        assert reply.kind is ReplyKind.INFO
        assert reply.text == "«Позвонить Ивану» уже отмечено как сделанное."
        assert reply.undo is None


class TestChoice:
    @pytest.fixture
    async def ivan(self, dialog: DialogHarness) -> list[int]:
        return [
            (await dialog.add_event(EventType.MEETING, title, starts_at)).id
            for title, starts_at in [
                ("Встреча с Иваном по CRM", at(TOMORROW, 10)),
                ("Встреча с Иваном по бюджету", at(TOMORROW, 14)),
                ("Встреча с Иваном и Ольгой", at(FRIDAY, 11)),
            ]
        ]

    async def offer(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси встречу с Иваном на четверг",
                target=about("встреча с Иваном", event_type=EventType.MEETING),
                when=When(date=THURSDAY),
            )
        )
        assert reply.kind is ReplyKind.CHOICE
        assert reply.text == "Нашёл 3 встречи. Какую перенести?"
        assert reply.pending is not None
        assert (reply.pending.expects, reply.pending.question) == (
            PendingExpectation.CHOICE,
            "Какую встречу перенести?",
        )
        assert [card.title for card in reply.choices] == [
            "Встреча с Иваном по CRM",
            "Встреча с Иваном по бюджету",
            "Встреча с Иваном и Ольгой",
        ]

    async def test_choose_by_number(self, dialog: DialogHarness, ivan: list[int]) -> None:
        await self.offer(dialog)

        reply = await dialog.say(choose("вторую", index=2))

        assert (
            reply.text
            == "Перенёс встречу «Встреча с Иваном по бюджету» на четверг, 29 октября, в 14:00."
        )
        assert reply.events[0].id == ivan[1]

    async def test_choose_by_title(self, dialog: DialogHarness, ivan: list[int]) -> None:
        await self.offer(dialog)

        reply = await dialog.say(choose("ту, что с Ольгой", title="с Ольгой"))

        assert reply.events[0].id == ivan[2]
        assert reply.events[0].starts_at == at(THURSDAY, 11)

    async def test_number_out_of_range_asks_again(
        self, dialog: DialogHarness, ivan: list[int]
    ) -> None:
        await self.offer(dialog)

        reply = await dialog.say(choose("пятую", index=5))

        assert reply.kind is ReplyKind.CHOICE
        assert (
            reply.text == "Такого варианта нет — назовите номер от 1 до 3. Какую встречу перенести?"
        )
        assert len(reply.choices) == 3

    async def test_choices_are_focus_in_order(self, dialog: DialogHarness, ivan: list[int]) -> None:
        await self.offer(dialog)

        assert dialog.state is not None and dialog.state.last_event_ids[:3] == ivan

    async def test_options_are_numbered_by_date_undated_last(self, dialog: DialogHarness) -> None:
        undated = await dialog.add_event(EventType.TASK, "Позвонить Ивану")
        friday = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(FRIDAY, 10))
        past = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(date(2026, 9, 1), 10))
        tomorrow = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(TOMORROW, 10))

        reply = await dialog.say(
            change(Action.DELETE, "Удали звонок Ивану", target=about("позвонить Ивану"))
        )

        expected = [past.id, tomorrow.id, friday.id, undated.id]
        assert [card.id for card in reply.choices] == expected
        assert dialog.state is not None and dialog.state.last_event_ids[:4] == expected

    async def test_more_than_five_keeps_most_timely(self, dialog: DialogHarness) -> None:
        old = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(date(2025, 1, 10), 10))
        upcoming = [
            (await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(day, 10))).id
            for day in (date(2026, 11, 20), FRIDAY, TOMORROW, date(2026, 11, 5), THURSDAY)
        ]

        reply = await dialog.say(
            change(Action.DELETE, "Удали звонок Ивану", target=about("позвонить Ивану"))
        )

        shown = [card.id for card in reply.choices]
        assert old.id not in shown
        assert shown == [upcoming[2], upcoming[4], upcoming[1], upcoming[3], upcoming[0]]

    async def test_choice_is_capped_at_five(self, dialog: DialogHarness) -> None:
        for hour in range(9, 16):
            await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(FRIDAY, hour))

        reply = await dialog.say(
            change(Action.DELETE, "Удали звонок Ивану", target=about("позвонить Ивану"))
        )

        assert len(reply.choices) == 5
        assert reply.text == "Подходит несколько записей, вот самые похожие. Какую удалить?"

    async def test_many_equal_records_keep_nearest_in_choice(self, dialog: DialogHarness) -> None:
        """60 одинаковых записей: ближайшая создана последней и всё равно среди вариантов."""
        for week in range(1, 60):
            await dialog.add_event(
                EventType.TASK, "Позвонить Ивану", at(TOMORROW, 10) + timedelta(weeks=week)
            )
        nearest = await dialog.add_event(EventType.TASK, "Позвонить Ивану", at(TOMORROW, 10))

        reply = await dialog.say(
            change(Action.DELETE, "Удали звонок Ивану", target=about("позвонить Ивану"))
        )

        assert reply.choices[0].id == nearest.id

    async def test_deny_choice(self, dialog: DialogHarness, ivan: list[int]) -> None:
        await self.offer(dialog)

        reply = await dialog.say(simple(Action.DENY, "никакую"))

        assert reply.text == "Хорошо, ничего не меняю."

    async def test_chosen_delete_still_asks_confirmation(
        self, dialog: DialogHarness, ivan: list[int]
    ) -> None:
        await dialog.say(
            change(Action.DELETE, "Удали встречу с Иваном", target=about("встреча с Иваном"))
        )

        reply = await dialog.say(choose("первую", index=1))

        assert reply.kind is ReplyKind.CONFIRM_REQUEST
        assert dialog.event(ivan[0]) is not None


class TestReschedule:
    async def test_time_only_keeps_date_and_duration(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(
            EventType.MEETING, "Демо", at(TOMORROW, 10), ends_at=at(TOMORROW, 11, 30)
        )
        await dialog.say(listing("Что завтра?"))

        reply = await dialog.say(move("Сдвинь демо на 16:00", about("демо"), time=time(16)))

        [card] = reply.events
        assert (card.id, card.starts_at, card.ends_at) == (
            meeting.id,
            at(TOMORROW, 16),
            at(TOMORROW, 17, 30),
        )

    async def test_date_only_keeps_time(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.REMINDER, "Позвонить маме", at(TOMORROW, 9, 30))

        reply = await dialog.say(
            move("Перенеси звонок маме на пятницу", about("позвонить маме"), date=FRIDAY)
        )

        assert reply.text == "Перенёс напоминание «Позвонить маме» на пятницу, 30 октября, в 9:30."

    async def test_task_without_time_stays_without_time(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Отчёт", at(TOMORROW, 0), has_time=False)

        reply = await dialog.say(move("Перенеси отчёт на пятницу", about("отчёт"), date=FRIDAY))

        assert (reply.events[0].starts_at, reply.events[0].has_time) == (at(FRIDAY, 0), False)

    async def test_task_to_next_week_is_due_sunday(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Отчёт", at(TOMORROW, 0), has_time=False)

        reply = await dialog.say(
            move("Перенеси отчёт на следующую неделю", about("отчёт"), week_of=NEXT_MONDAY)
        )

        assert reply.events[0].starts_at == at(date(2026, 11, 8), 23, 59)

    async def test_meeting_to_next_week_asks_day(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        question = await dialog.say(
            move("Перенеси демо на следующую неделю", about("демо"), week_of=NEXT_MONDAY)
        )
        reply = await dialog.say(answer("на вторник", date=date(2026, 11, 3)))

        assert question.text == "На какой день следующей недели перенести?"
        assert reply.events[0].starts_at == at(date(2026, 11, 3), 10)

    async def test_missing_new_time_is_asked(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        question = await dialog.say(
            change(Action.RESCHEDULE, "Перенеси демо", target=about("демо"))
        )
        reply = await dialog.say(answer("на 12", time=time(12)))

        assert question.text == "На когда перенести встречу «Демо»?"
        assert (
            question.pending is not None and question.pending.expects is PendingExpectation.DATETIME
        )
        assert reply.events[0].starts_at == at(TOMORROW, 12)

    async def test_conflict_on_move(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 15))
        demo = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        asked = await dialog.say(move("Перенеси демо на 15:30", about("демо"), time=time(15, 30)))
        moved = await dialog.say(simple(Action.CONFIRM, "да"))

        assert asked.kind is ReplyKind.CONFIRM_REQUEST
        assert asked.text.endswith("Всё равно перенести?")
        assert [card.title for card in asked.conflicts] == ["Планёрка"]
        assert moved.events[0].id == demo.id
        assert moved.events[0].starts_at == at(TOMORROW, 15, 30)

    async def test_deny_conflicting_move(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 15))
        demo = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        await dialog.say(move("Перенеси демо на 15:30", about("демо"), time=time(15, 30)))
        reply = await dialog.say(simple(Action.DENY, "нет"))

        assert reply.text == "Хорошо, оставляю как было."
        record = dialog.event(demo.id)
        assert record is not None and record.starts_at == at(TOMORROW, 10)

    async def test_meeting_does_not_conflict_with_itself(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        reply = await dialog.say(move("Сдвинь демо на 10:30", about("демо"), time=time(10, 30)))

        assert reply.kind is ReplyKind.CONFIRMATION


class TestRescheduleOldAndNewMoment:
    """F11: прежние день и время ищут запись, новые — куда её перенести."""

    async def test_old_time_picks_record_new_time_moves_it(self, dialog: DialogHarness) -> None:
        at_ten = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 10))
        at_three = await dialog.add_event(EventType.MEETING, "Созвон", at(TOMORROW, 15))

        reply = await dialog.say(
            move(
                "Перенеси завтрашний созвон в 15:00 на 17:00",
                about("созвон", when=When(date=TOMORROW, time=time(15))),
                time=time(17),
            )
        )

        assert reply.events[0].id == at_three.id
        assert dialog.event(at_three.id).starts_at == at(TOMORROW, 17)
        assert dialog.event(at_ten.id).starts_at == at(TOMORROW, 10)

    async def test_record_named_only_by_day_and_time(self, dialog: DialogHarness) -> None:
        """«Перенеси завтрашнюю встречу в 10 на пятницу в 12» — без названия записи."""
        at_ten = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))
        other = await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 15))
        await dialog.add_event(EventType.TASK, "Отчёт", at(TOMORROW, 10))

        reply = await dialog.say(
            move(
                "Перенеси завтрашнюю встречу в 10 на пятницу в 12",
                TargetRef(event_type=EventType.MEETING, when=When(date=TOMORROW, time=time(10))),
                date=FRIDAY,
                time=time(12),
            )
        )

        assert reply.kind is ReplyKind.CONFIRMATION
        assert reply.events[0].id == at_ten.id
        assert dialog.event(at_ten.id).starts_at == at(FRIDAY, 12)
        assert dialog.event(other.id).starts_at == at(TOMORROW, 15)

    async def test_nothing_at_named_moment_changes_nothing(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 11))

        reply = await dialog.say(
            move(
                "Перенеси завтрашнюю встречу в 10 на 12",
                TargetRef(event_type=EventType.MEETING, when=When(date=TOMORROW, time=time(10))),
                time=time(12),
            )
        )

        assert reply.kind is ReplyKind.INFO
        assert reply.text.startswith("Не нашёл записи в названное время.")
        assert dialog.event(meeting.id).starts_at == at(TOMORROW, 11)

    async def test_several_at_named_moment_are_offered(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 10))

        reply = await dialog.say(
            move(
                "Перенеси встречу в 10 на 12",
                TargetRef(event_type=EventType.MEETING, when=When(time=time(10))),
                time=time(12),
            )
        )

        assert reply.kind is ReplyKind.CHOICE
        assert reply.text == "Нашёл 2 встречи. Какую перенести?"


class TestRescheduleDuration:
    """F11: названная при переносе длительность меняет конец встречи."""

    async def test_named_duration_is_applied(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 15))

        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на 17:00 на полчаса",
                target=about("демо"),
                when=When(time=time(17)),
                duration_minutes=30,
            )
        )

        record = dialog.event(meeting.id)
        assert (record.starts_at, record.ends_at) == (at(TOMORROW, 17), at(TOMORROW, 17, 30))
        assert reply.text == "Перенёс встречу «Демо» на завтра, 27 октября, в 17:00."
        assert reply.events[0].ends_at == at(TOMORROW, 17, 30)

    async def test_without_duration_original_is_kept(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(
            EventType.MEETING, "Демо", at(TOMORROW, 15), ends_at=at(TOMORROW, 17)
        )

        await dialog.say(move("Перенеси демо на пятницу", about("демо"), date=FRIDAY))

        record = dialog.event(meeting.id)
        assert (record.starts_at, record.ends_at) == (at(FRIDAY, 15), at(FRIDAY, 17))

    async def test_shorter_meeting_does_not_conflict_after_its_end(
        self, dialog: DialogHarness
    ) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 17, 30))
        await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на 17:00 на полчаса",
                target=about("демо"),
                when=When(time=time(17)),
                duration_minutes=30,
            )
        )

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_conflict_confirmation_keeps_new_duration(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 17, 15))
        demo = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))

        asked = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на 17:00 на полчаса",
                target=about("демо"),
                when=When(time=time(17)),
                duration_minutes=30,
            )
        )
        await dialog.say(simple(Action.CONFIRM, "да"))

        assert asked.kind is ReplyKind.CONFIRM_REQUEST
        record = dialog.event(demo.id)
        assert (record.starts_at, record.ends_at) == (at(TOMORROW, 17), at(TOMORROW, 17, 30))

    async def test_undo_restores_previous_duration(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 15))

        await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на 17:00 на полчаса",
                target=about("демо"),
                when=When(time=time(17)),
                duration_minutes=30,
            )
        )
        await dialog.say(simple(Action.UNDO, "отмени"))

        record = dialog.event(meeting.id)
        assert (record.starts_at, record.ends_at) == (at(TOMORROW, 15), at(TOMORROW, 16))


class TestSeveralCommands:
    """F11: выполняется первая команда, остальные честно называются, а не теряются."""

    async def test_rest_of_phrase_is_named_in_reply(self, dialog: DialogHarness) -> None:
        planning = await dialog.add_event(EventType.MEETING, "Планёрка", at(TOMORROW, 10))
        petr = await dialog.add_event(EventType.MEETING, "Встреча с Петром", at(TOMORROW, 15))

        reply = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси планёрку на 11 и удали встречу с Петром",
                target=about("планёрка"),
                when=When(time=time(11)),
                unhandled="удали встречу с Петром",
            )
        )

        assert reply.text == (
            "Перенёс встречу «Планёрка» на завтра, 27 октября, в 11:00. "
            "А «удали встречу с Петром» пока не сделал: выполняю по одной команде — "
            "скажите это отдельно."
        )
        assert dialog.event(planning.id).starts_at == at(TOMORROW, 11)
        assert dialog.event(petr.id) is not None
        assert dialog.state is not None and dialog.state.recent[-1]["text"] == reply.text

    async def test_rest_is_named_with_question_too(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            Intent(
                Action.CREATE,
                "Создай встречу и задачу купить билеты",
                event_type=EventType.MEETING,
                unhandled="задачу купить билеты",
            )
        )

        assert reply.kind is ReplyKind.CLARIFICATION
        assert reply.text.endswith(
            "А «задачу купить билеты» пока не сделал: выполняю по одной "
            "команде — скажите это отдельно."
        )
        assert reply.pending is not None and reply.pending.question == "Как назвать встречу?"


class TestRenameCompleteDelete:
    async def test_rename_asks_new_title(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Отчёт")

        question = await dialog.say(
            change(Action.RENAME, "Переименуй отчёт", target=about("отчёт"))
        )
        reply = await dialog.say(answer("квартальный отчёт для Ольги"))

        assert question.text == "Как теперь назвать задачу «Отчёт»?"
        assert (
            reply.text == "Переименовал: «Отчёт» теперь называется «Квартальный отчёт для Ольги»."
        )

    async def test_complete(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(
            EventType.TASK, "Купить билеты", at(FRIDAY, 0), has_time=False
        )

        reply = await dialog.say(
            change(Action.COMPLETE, "Билеты купил", target=about("купить билеты"))
        )

        assert reply.kind is ReplyKind.CONFIRMATION
        record = dialog.event(task.id)
        assert record is not None and record.status is EventStatus.DONE

    async def test_delete_always_asks(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.MEETING, "Разбор макетов с Ольгой", at(TODAY, 17))

        asked = await dialog.say(
            change(Action.DELETE, "Удали разбор макетов", target=about("разбор макетов"))
        )

        assert asked.kind is ReplyKind.CONFIRM_REQUEST
        assert (
            asked.text
            == "Удалить встречу «Разбор макетов с Ольгой» — сегодня, 26 октября, в 17:00?"
        )
        assert [card.id for card in asked.events] == [task.id]
        assert dialog.event(task.id) is not None

    async def test_delete_confirmed(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.TASK, "Купить билеты")
        await dialog.say(change(Action.DELETE, "Удали билеты", target=about("билеты")))

        reply = await dialog.say(simple(Action.CONFIRM, "да, удаляй"))

        assert reply.text == "Удалил задачу «Купить билеты»."
        assert reply.undo is not None
        assert dialog.event(task.id) is None

    async def test_delete_denied(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.TASK, "Купить билеты")
        await dialog.say(change(Action.DELETE, "Удали билеты", target=about("билеты")))

        reply = await dialog.say(simple(Action.DENY, "нет, оставь"))

        assert reply.text == "Хорошо, не удаляю."
        assert dialog.event(task.id) is not None

    async def test_confirm_after_target_vanished(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.TASK, "Купить билеты")
        await dialog.say(change(Action.DELETE, "Удали билеты", target=about("билеты")))
        await dialog.storage.events.delete(dialog.profile_id, task.id)

        reply = await dialog.say(simple(Action.CONFIRM, "да"))

        assert reply.text == "Этой записи уже нет."

    async def test_other_profile_records_are_invisible(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Купить билеты", profile_id=uuid4())

        reply = await dialog.say(change(Action.DELETE, "Удали билеты", target=about("билеты")))

        assert reply.text.startswith("Не нашёл ничего похожего")


class TestPronounAfterList:
    """«Что у меня сегодня?» (несколько записей) → «Отметь её» — какую? Переспросить."""

    @pytest.fixture
    async def two_reminders(self, dialog: DialogHarness) -> list[int]:
        later = await dialog.add_event(EventType.REMINDER, "Полить цветы", at(TODAY, 19))
        earlier = await dialog.add_event(EventType.REMINDER, "Позвонить маме", at(TODAY, 16, 45))
        await dialog.say(listing("Что у меня сегодня?"))
        return [earlier.id, later.id]

    async def test_it_after_list_of_two_asks_which(
        self, dialog: DialogHarness, two_reminders: list[int]
    ) -> None:
        reply = await dialog.say(change(Action.COMPLETE, "Отметь её выполненной", target=it()))

        assert reply.kind is ReplyKind.CHOICE
        assert reply.text == "Какое напоминание отметить сделанным?"
        assert [card.id for card in reply.choices] == two_reminders
        statuses = [dialog.event(event_id) for event_id in two_reminders]
        assert all(record is not None and record.status is EventStatus.OPEN for record in statuses)

    async def test_choice_then_completes_chosen(
        self, dialog: DialogHarness, two_reminders: list[int]
    ) -> None:
        await dialog.say(change(Action.COMPLETE, "Отметь её выполненной", target=it()))

        reply = await dialog.say(choose("вторую", index=2))

        assert reply.text == "Отметил как сделанное: «Полить цветы»."
        assert dialog.state is not None and dialog.state.focus_peers == 1

    async def test_list_of_one_acts_at_once(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.REMINDER, "Позвонить маме", at(TODAY, 16, 45))
        await dialog.say(listing("Что у меня сегодня?"))

        reply = await dialog.say(change(Action.COMPLETE, "Отметь её", target=it()))

        assert reply.kind is ReplyKind.CONFIRMATION

    async def test_named_type_narrows_to_single(self, dialog: DialogHarness) -> None:
        meeting = await dialog.add_event(EventType.MEETING, "Демо", at(TODAY, 15))
        await dialog.add_event(EventType.REMINDER, "Позвонить маме", at(TODAY, 16, 45))
        await dialog.say(listing("Что у меня сегодня?"))

        reply = await dialog.say(
            change(
                Action.COMPLETE,
                "Отметь эту встречу",
                target=TargetRef(last=True, event_type=EventType.MEETING),
            )
        )

        assert reply.kind is ReplyKind.CONFIRMATION
        assert reply.events[0].id == meeting.id

    async def test_created_record_after_list_is_it(
        self, dialog: DialogHarness, two_reminders: list[int]
    ) -> None:
        created = await dialog.say(create("Купить хлеб", EventType.TASK, "Купить хлеб"))

        reply = await dialog.say(change(Action.DELETE, "Удали её", target=it()))

        assert reply.kind is ReplyKind.CONFIRM_REQUEST
        assert reply.events[0].id == created.events[0].id

    async def test_search_list_asks_but_when_answer_names_one(self, dialog: DialogHarness) -> None:
        older = await dialog.add_event(EventType.MEETING, "Демо", at(date(2026, 9, 1), 10))
        await dialog.add_event(EventType.MEETING, "Демо", at(date(2026, 11, 5), 10))

        await dialog.say(search_for("Найди демо", TimeScope.ANY))
        found_list = await dialog.say(change(Action.DELETE, "Удали её", target=it()))
        await dialog.say(search_for("Когда было демо?", TimeScope.PAST))
        named = await dialog.say(change(Action.DELETE, "Удали её", target=it()))

        assert found_list.kind is ReplyKind.CHOICE
        assert named.kind is ReplyKind.CONFIRM_REQUEST
        assert named.events[0].id == older.id

    async def test_peers_are_saved_in_state(
        self, dialog: DialogHarness, two_reminders: list[int]
    ) -> None:
        assert dialog.state is not None
        assert (dialog.state.last_event_ids[:2], dialog.state.focus_peers) == (two_reminders, 2)


def search_for(text: str, scope: TimeScope) -> Intent:
    return Intent(Action.SEARCH, text, query="демо", time_scope=scope)
