"""Список за период и поиск по смыслу: тексты ответов, фильтры, группировка по названию."""

from datetime import date

import pytest

from app.core.enums import EventStatus, EventType, ReplyKind
from app.nlu.interfaces import Period, TimeScope
from tests.unit.dialog.support import (
    THURSDAY,
    TODAY,
    TOMORROW,
    DialogHarness,
    at,
    day_period,
    listing,
    search,
)


class TestList:
    async def test_default_period_is_today(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TODAY, 17))
        await dialog.add_event(EventType.MEETING, "Завтрашняя", at(TOMORROW, 10))

        reply = await dialog.say(listing("Что у меня?"))

        assert [card.title for card in reply.events] == ["Планёрка"]
        assert reply.period is not None and reply.period.label == "сегодня"
        assert (reply.period.start, reply.period.end) == (at(TODAY, 0), at(TOMORROW, 0))

    async def test_empty_today(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(listing("Что у меня сегодня?"))

        assert reply.kind is ReplyKind.LIST
        assert reply.text == "На сегодня ничего нет."
        assert reply.events == []

    async def test_empty_with_type(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Отчёт", at(TODAY, 18))

        reply = await dialog.say(listing("Встречи сегодня?", event_type=EventType.MEETING))

        assert reply.text == "На сегодня встреч нет."

    async def test_empty_period_with_preposition(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(
            listing("Что на завтра?", period=day_period(TOMORROW, "на завтра"))
        )

        assert reply.text == "На завтра ничего нет."

    async def test_single_event(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Планёрка", at(TODAY, 17))

        reply = await dialog.say(listing("Что у меня сегодня?"))

        assert reply.text == "Сегодня у вас одна встреча: «Планёрка» в 17:00."

    async def test_nearest_skips_passed_and_done(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Утренняя", at(TODAY, 9))
        await dialog.add_event(
            EventType.REMINDER, "Выполненное", at(TODAY, 13), status=EventStatus.DONE
        )
        await dialog.add_event(EventType.REMINDER, "Позвонить маме", at(TODAY, 19))

        reply = await dialog.say(listing("Что у меня сегодня?"))

        assert reply.text == (
            "Сегодня у вас 3 дела: встреча и 2 напоминания. "
            "Ближайшее — «Позвонить маме» в 19:00. Сделано 1 из 3."
        )

    async def test_past_period_has_no_nearest(self, dialog: DialogHarness) -> None:
        yesterday = date(2026, 10, 25)
        await dialog.add_event(EventType.TASK, "Отчёт", at(yesterday, 10), status=EventStatus.DONE)
        await dialog.add_event(EventType.TASK, "Звонок", at(yesterday, 11), status=EventStatus.DONE)

        reply = await dialog.say(listing("Что было вчера?", period=day_period(yesterday, "вчера")))

        assert reply.text == "Вчера у вас 2 задачи. Всё уже сделано."

    async def test_status_filter(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Сделано", at(TODAY, 10), status=EventStatus.DONE)
        await dialog.add_event(EventType.TASK, "Не сделано", at(TODAY, 11))

        reply = await dialog.say(listing("Что я не сделал?", status=EventStatus.OPEN))

        assert [card.title for card in reply.events] == ["Не сделано"]

    async def test_week_nearest_names_the_day(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Созвон", at(THURSDAY, 11))
        await dialog.add_event(EventType.MEETING, "Демо", at(THURSDAY, 15))
        week = Period(at(TODAY, 0), at(date(2026, 11, 2), 0), "на этой неделе")

        reply = await dialog.say(listing("Что на неделе?", period=week))

        assert reply.text == (
            "На этой неделе у вас 2 встречи. Ближайшая — «Созвон» в четверг, 29 октября, в 11:00."
        )

    async def test_listed_events_become_focus(self, dialog: DialogHarness) -> None:
        first = await dialog.add_event(EventType.MEETING, "Планёрка", at(TODAY, 15))
        second = await dialog.add_event(EventType.MEETING, "Демо", at(TODAY, 17))

        await dialog.say(listing("Что у меня сегодня?"))

        assert dialog.state is not None
        assert dialog.state.last_event_ids == [first.id, second.id]


class TestSearch:
    @pytest.fixture
    async def ivan_meetings(self, dialog: DialogHarness) -> dict[str, int]:
        title = "Встреча с Иваном по CRM"
        ids = {
            "old": (await dialog.add_event(EventType.MEETING, title, at(date(2025, 6, 2), 10))).id,
            "last": (await dialog.add_event(EventType.MEETING, title, at(date(2026, 9, 1), 14))).id,
            "next": (
                await dialog.add_event(EventType.MEETING, title, at(date(2026, 11, 5), 12))
            ).id,
            "later": (
                await dialog.add_event(EventType.MEETING, title, at(date(2027, 1, 10), 9))
            ).id,
        }
        await dialog.add_event(EventType.TASK, "Отправить итоги встречи Иваном")
        return ids

    async def test_past_takes_latest_passed_of_first_group(
        self, dialog: DialogHarness, ivan_meetings: dict[str, int]
    ) -> None:
        reply = await dialog.say(
            search(
                "Когда была встреча с Иваном?",
                "встреча Иван",
                event_type=EventType.MEETING,
                time_scope=TimeScope.PAST,
            )
        )

        assert reply.kind is ReplyKind.SEARCH_RESULTS
        assert (
            reply.text
            == "Последняя встреча «Встреча с Иваном по CRM» была 1 сентября 2026 в 14:00."
        )
        assert reply.events[0].id == ivan_meetings["last"]
        assert len(reply.events) == 5

    async def test_future_takes_nearest_upcoming(
        self, dialog: DialogHarness, ivan_meetings: dict[str, int]
    ) -> None:
        reply = await dialog.say(
            search(
                "Когда будет встреча с Иваном?",
                "встреча Иван",
                event_type=EventType.MEETING,
                time_scope=TimeScope.FUTURE,
            )
        )

        assert reply.text == "Ближайшая встреча «Встреча с Иваном по CRM» будет 5 ноября в 12:00."
        assert reply.events[0].id == ivan_meetings["next"]

    async def test_past_without_passed_falls_back_to_future(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.MEETING, "Демо для Пульса", at(TOMORROW, 11))

        reply = await dialog.say(search("Когда было демо?", "демо", time_scope=TimeScope.PAST))

        assert reply.text == (
            "Раньше такого не было. "
            "Ближайшая встреча «Демо для Пульса» будет завтра, 27 октября, в 11:00."
        )

    async def test_future_without_upcoming_falls_back_to_past(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.REMINDER, "Продлить полис", at(date(2026, 1, 15), 10))

        reply = await dialog.say(
            search("Когда продлевать полис?", "полис", time_scope=TimeScope.FUTURE)
        )

        assert reply.text == (
            "Впереди такого нет. "
            "Последнее напоминание «Продлить полис» было 15 января 2026 в 10:00."
        )

    async def test_undated_task(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Разобрать балкон")

        reply = await dialog.say(
            search("Когда я хотел разобрать балкон?", "балкон", time_scope=TimeScope.PAST)
        )

        assert reply.text == "Нашёл задачу «Разобрать балкон» — без срока."

    async def test_nothing_found(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Купить билеты")

        reply = await dialog.say(search("Найди отпуск", "отпуск"))

        assert reply.kind is ReplyKind.INFO
        assert reply.text == "Не нашёл похожих записей. Попробуйте сказать иначе."

    async def test_any_scope_counts_records(
        self, dialog: DialogHarness, ivan_meetings: dict[str, int]
    ) -> None:
        reply = await dialog.say(search("Найди встречи с Иваном", "встреча Иван"))

        assert reply.text.startswith(
            "Нашёл 5 записей. Ближе всего — встреча «Встреча с Иваном по CRM»"
        )

    async def test_preferred_type_is_passed_to_ranking(self, dialog: DialogHarness) -> None:
        await dialog.say(search("Найди встречу с Иваном", "Иван", event_type=EventType.MEETING))

        assert dialog.ranker.preferred_types == [EventType.MEETING]

    async def test_period_filter_limits_search(self, dialog: DialogHarness) -> None:
        await dialog.add_event(EventType.TASK, "Договор с Вектором", at(date(2025, 3, 3), 10))
        recent = await dialog.add_event(EventType.TASK, "Договор аренды", at(date(2026, 10, 5), 10))
        october = Period(at(date(2026, 10, 1), 0), at(date(2026, 11, 1), 0), "в октябре")

        reply = await dialog.say(search("Договор в октябре", "договор", period=october))

        assert [card.id for card in reply.events] == [recent.id]

    async def test_found_events_become_focus(self, dialog: DialogHarness) -> None:
        found = await dialog.add_event(EventType.TASK, "Подготовить презентацию", at(TOMORROW, 10))

        await dialog.say(search("Найди презентацию", "презентация"))

        assert dialog.state is not None and dialog.state.last_event_ids[0] == found.id
