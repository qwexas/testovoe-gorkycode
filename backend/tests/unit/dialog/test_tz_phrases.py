"""Все фразы-примеры из ТЗ: разбор заготовлен, проверяется действие и ответ ассистента.

Сегодня в тестах — понедельник, 26 октября 2026, 12:00 по Москве.
"""

from datetime import date, time, timedelta

import pytest

from app.core.enums import EventStatus, EventType, PendingExpectation, ReplyKind
from app.nlu.interfaces import Action, Period, TimeScope, When
from tests.unit.dialog.support import (
    FRIDAY,
    NEXT_MONDAY,
    SUNDAY,
    THURSDAY,
    TODAY,
    TOMORROW,
    DialogHarness,
    about,
    answer,
    at,
    change,
    create,
    day_period,
    it,
    listing,
    search,
)


class TestCreateTaskOrReminder:
    """ТЗ 1: «Напомни мне завтра в 10 утра позвонить Ивану» и др."""

    async def test_remind_tomorrow_at_ten(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Напомни мне завтра в 10 утра позвонить Ивану",
                EventType.REMINDER,
                "позвонить Ивану",
                date=TOMORROW,
                time=time(10, 0),
            )
        )

        assert reply.kind is ReplyKind.CONFIRMATION
        assert reply.text == "Напоминание «Позвонить Ивану» — завтра, 27 октября, в 10:00."
        [event] = reply.events
        assert (event.type, event.starts_at, event.has_time) == (
            EventType.REMINDER,
            at(TOMORROW, 10),
            True,
        )
        assert reply.undo is not None

    async def test_report_on_friday_has_date_without_time(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "В пятницу нужно отправить отчет", EventType.TASK, "Отправить отчет", date=FRIDAY
            )
        )

        assert reply.text == "Задача «Отправить отчет» — в пятницу, 30 октября."
        [event] = reply.events
        assert (event.starts_at, event.has_time) == (at(FRIDAY, 0), False)

    async def test_tickets_until_end_of_week(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Поставь задачу купить билеты до конца недели",
                EventType.TASK,
                "купить билеты",
                date=SUNDAY,
                time=time(23, 59),
            )
        )

        assert reply.text == "Задача «Купить билеты» — в воскресенье, 1 ноября, в 23:59."
        assert reply.events[0].starts_at == at(SUNDAY, 23, 59)


class TestCreateMeeting:
    """ТЗ 2: «Добавь встречу с командой завтра в 15:00», «В четверг в 11 у меня встреча…»."""

    async def test_team_meeting_tomorrow(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Добавь встречу с командой завтра в 15:00",
                EventType.MEETING,
                "Встреча с командой",
                date=TOMORROW,
                time=time(15, 0),
            )
        )

        assert reply.text == "Встреча «Встреча с командой» — завтра, 27 октября, в 15:00."
        [event] = reply.events
        assert (event.starts_at, event.ends_at) == (at(TOMORROW, 15), at(TOMORROW, 16))

    async def test_designer_meeting_on_thursday(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "В четверг в 11 у меня встреча с дизайнером",
                EventType.MEETING,
                "Встреча с дизайнером",
                date=THURSDAY,
                time=time(11, 0),
            )
        )

        assert reply.text == "Встреча «Встреча с дизайнером» — в четверг, 29 октября, в 11:00."


class TestListPeriod:
    """ТЗ 3: «Что у меня сегодня?», «Есть ли у меня встречи сегодня?» и др."""

    @pytest.fixture
    async def planned(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TODAY, 10))
        await dialog.add_event(EventType.MEETING, "Разбор макетов с Ольгой", at(TODAY, 17))
        await dialog.add_event(EventType.TASK, "Отправить отчёт", at(TODAY, 0), has_time=False)
        await dialog.add_event(EventType.TASK, "Купить билеты", at(TOMORROW, 0), has_time=False)
        await dialog.add_event(EventType.MEETING, "Созвон с партнёром", at(THURSDAY, 11))

    @pytest.mark.parametrize(
        "text", ["Что у меня сегодня?", "Какие планы на сегодня?", "Что запланировано сегодня?"]
    )
    async def test_today_in_different_words(
        self, dialog: DialogHarness, planned: None, text: str
    ) -> None:
        reply = await dialog.say(listing(text))

        assert reply.kind is ReplyKind.LIST
        assert reply.text == (
            "Сегодня у вас 3 дела: 2 встречи и задача. "
            "Ближайшее — «Разбор макетов с Ольгой» в 17:00."
        )
        assert [card.title for card in reply.events] == [
            "Отправить отчёт",
            "Планёрка",
            "Разбор макетов с Ольгой",
        ]
        assert reply.period is not None
        assert (reply.period.start, reply.period.label) == (at(TODAY, 0), "сегодня")

    @pytest.mark.parametrize(
        "text", ["Есть ли у меня встречи сегодня?", "Покажи мои встречи на сегодня"]
    )
    async def test_meetings_today(self, dialog: DialogHarness, planned: None, text: str) -> None:
        reply = await dialog.say(listing(text, event_type=EventType.MEETING))

        assert (
            reply.text == "Сегодня у вас 2 встречи. Ближайшая — «Разбор макетов с Ольгой» в 17:00."
        )
        assert {card.type for card in reply.events} == {EventType.MEETING}

    async def test_tasks_for_tomorrow(self, dialog: DialogHarness, planned: None) -> None:
        reply = await dialog.say(
            listing(
                "Какие задачи у меня на завтра?",
                event_type=EventType.TASK,
                period=day_period(TOMORROW, "на завтра"),
            )
        )

        assert reply.text == "На завтра у вас одна задача: «Купить билеты» завтра, 27 октября."
        assert [card.title for card in reply.events] == ["Купить билеты"]

    async def test_this_week(self, dialog: DialogHarness, planned: None) -> None:
        week = Period(at(TODAY, 0), at(NEXT_MONDAY, 0), "на этой неделе")

        reply = await dialog.say(listing("Что запланировано на эту неделю?", period=week))

        assert reply.text.startswith("На этой неделе у вас 5 дел: 3 встречи и 2 задачи.")
        assert len(reply.events) == 5


class TestSearchOldRecords:
    """ТЗ 4: «Найди задачу про презентацию», «Когда у меня была встреча с Иваном?» и др."""

    async def test_task_about_presentation(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.TASK, "Подготовить презентацию", at(date(2026, 4, 8), 9, 45)
        )
        await dialog.add_event(EventType.TASK, "Купить билеты")

        reply = await dialog.say(
            search("Найди задачу про презентацию", "презентация", event_type=EventType.TASK)
        )

        assert reply.kind is ReplyKind.SEARCH_RESULTS
        assert reply.text == (
            "Нашёл одну запись: задача «Подготовить презентацию», 8 апреля 2026 в 9:45."
        )
        assert dialog.ranker.preferred_types == [EventType.TASK]

    async def test_when_was_meeting_with_ivan(self, dialog: DialogHarness) -> None:
        title = "Встреча с Иваном по презентации"
        await dialog.add_event(EventType.MEETING, title, at(date(2025, 12, 30), 11))
        latest = await dialog.add_event(EventType.MEETING, title, at(date(2026, 3, 5), 15, 45))
        await dialog.add_event(EventType.MEETING, title, at(TOMORROW, 15))
        await dialog.add_event(EventType.TASK, "Отправить итоги встречи Ивану")

        reply = await dialog.say(
            search(
                "Когда у меня была встреча с Иваном?",
                "встреча с Иваном",
                event_type=EventType.MEETING,
                time_scope=TimeScope.PAST,
            )
        )

        assert reply.text == (
            "Последняя встреча «Встреча с Иваном по презентации» была 5 марта 2026 в 15:45."
        )
        assert reply.events[0].id == latest.id

    async def test_contract_task_found_by_meaning(self, dialog: DialogHarness) -> None:
        await dialog.add_event(
            EventType.TASK, "Подписать договор с Вектором", at(FRIDAY, 0), has_time=False
        )
        await dialog.add_event(EventType.TASK, "Проверить договор аренды")

        reply = await dialog.say(
            search(
                "Я когда-то ставил задачу по договору, найди ее",
                "договор",
                event_type=EventType.TASK,
            )
        )

        assert reply.text == (
            "Нашёл 2 записи. Ближе всего — задача «Подписать договор с Вектором», "
            "в пятницу, 30 октября."
        )


class TestNaturalLanguage:
    """Относительные даты и уточняющий диалог из ТЗ."""

    async def test_clarification_example_from_tz(self, dialog: DialogHarness) -> None:
        question = await dialog.say(
            create(
                "Поставь встречу с Иваном завтра",
                EventType.MEETING,
                "Встреча с Иваном",
                date=TOMORROW,
            )
        )
        assert question.kind is ReplyKind.CLARIFICATION
        assert question.text == "На какое время поставить встречу?"
        assert question.pending is not None
        assert question.pending.expects is PendingExpectation.TIME

        created = await dialog.say(answer("в 15", time=time(15, 0)))

        assert created.kind is ReplyKind.CONFIRMATION
        assert created.text == "Встреча «Встреча с Иваном» — завтра, 27 октября, в 15:00."
        assert created.events[0].ends_at == at(TOMORROW, 16)
        assert dialog.state is not None and dialog.state.pending is None

    async def test_in_two_hours(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "Через два часа напомни выключить духовку",
                EventType.REMINDER,
                "Выключить духовку",
                date=TODAY,
                time=time(14, 0),
            )
        )

        assert reply.text == "Напоминание «Выключить духовку» — сегодня, 26 октября, в 14:00."

    async def test_day_after_tomorrow(self, dialog: DialogHarness) -> None:
        day_after = TOMORROW + timedelta(days=1)

        reply = await dialog.say(
            create("Послезавтра сдать отчёт", EventType.TASK, "Сдать отчёт", date=day_after)
        )

        assert reply.text == "Задача «Сдать отчёт» — послезавтра, 28 октября."

    async def test_task_next_week_is_due_sunday(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            create(
                "На следующей неделе оплатить счёт",
                EventType.TASK,
                "Оплатить счёт",
                week_of=NEXT_MONDAY,
            )
        )

        assert reply.text == "Задача «Оплатить счёт» — 8 ноября в 23:59."

    async def test_move_it_to_tomorrow(self, dialog: DialogHarness) -> None:
        """Бонус ТЗ: контекст диалога — «А перенеси её на завтра»."""
        await dialog.say(
            create(
                "Встреча с дизайнером сегодня в 16",
                EventType.MEETING,
                "Встреча с дизайнером",
                date=TODAY,
                time=time(16, 0),
            )
        )

        reply = await dialog.say(
            change(
                Action.RESCHEDULE, "А перенеси её на завтра", target=it(), when=When(date=TOMORROW)
            )
        )

        assert (
            reply.text == "Перенёс встречу «Встреча с дизайнером» на завтра, 27 октября, в 16:00."
        )
        assert (reply.events[0].starts_at, reply.events[0].ends_at) == (
            at(TOMORROW, 16),
            at(TOMORROW, 17),
        )

    async def test_complete_and_delete_by_voice(self, dialog: DialogHarness) -> None:
        """Бонусы ТЗ: отметка о выполнении и удаление голосом."""
        call = await dialog.add_event(EventType.REMINDER, "Позвонить Ивану", at(TOMORROW, 10))

        done = await dialog.say(
            change(
                Action.COMPLETE,
                "Отметь звонок Ивану как сделанный",
                target=about("позвонить Ивану"),
            )
        )
        asked = await dialog.say(change(Action.DELETE, "Удали его", target=it()))

        assert done.text == "Отметил как сделанное: «Позвонить Ивану»."
        record = dialog.event(call.id)
        assert record is not None and record.status is EventStatus.DONE
        assert asked.kind is ReplyKind.CONFIRM_REQUEST
        assert asked.text == "Удалить напоминание «Позвонить Ивану» — завтра, 27 октября, в 10:00?"
