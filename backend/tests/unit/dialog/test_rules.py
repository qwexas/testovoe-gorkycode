"""Правила времени диалога: чего не хватает (Q30) и что по умолчанию (Q31), по правилу на тест."""

from datetime import date, time, timedelta

import pytest

from app.core.dialog.rules import (
    creation_draft,
    creation_question,
    merge_answer,
    merge_when,
    rescheduled_schedule,
    tidy_title,
)
from app.core.enums import EventType, PendingExpectation
from app.core.events import EventCard
from app.nlu.interfaces import Action, Intent, When
from tests.unit.dialog.support import NEXT_MONDAY, NOW, SUNDAY, TODAY, TOMORROW, at, card, create


def expects(intent: Intent) -> PendingExpectation | None:
    question = creation_question(intent, TODAY)
    return None if question is None else question.expects


class TestQ30WhatIsMissing:
    def test_task_needs_only_title(self) -> None:
        assert expects(create("", EventType.TASK, "Купить хлеб")) is None

    def test_any_type_needs_title(self) -> None:
        assert expects(create("", EventType.TASK, None)) is PendingExpectation.TITLE

    def test_reminder_without_anything(self) -> None:
        assert expects(create("", EventType.REMINDER, "Позвонить")) is PendingExpectation.DATETIME

    def test_reminder_without_time(self) -> None:
        intent = create("", EventType.REMINDER, "Позвонить", date=TOMORROW)

        assert expects(intent) is PendingExpectation.TIME

    def test_reminder_with_time_only_is_enough(self) -> None:
        assert expects(create("", EventType.REMINDER, "Позвонить", time=time(9))) is None

    def test_meeting_without_time(self) -> None:
        intent = create("", EventType.MEETING, "Встреча", date=TOMORROW)

        assert expects(intent) is PendingExpectation.TIME

    def test_meeting_without_date(self) -> None:
        assert (
            expects(create("", EventType.MEETING, "Встреча", time=time(15)))
            is PendingExpectation.DATE
        )

    def test_meeting_next_week_asks_day(self) -> None:
        intent = create("", EventType.MEETING, "Встреча", week_of=NEXT_MONDAY, time=time(15))

        assert expects(intent) is PendingExpectation.DATE


class TestQ31Defaults:
    def test_meeting_lasts_sixty_minutes(self) -> None:
        draft = creation_draft(
            create("", EventType.MEETING, "Встреча", date=TOMORROW, time=time(15)), NOW
        )

        assert draft.ends_at is not None and draft.starts_at is not None
        assert draft.ends_at - draft.starts_at == timedelta(minutes=60)

    def test_named_duration_wins(self) -> None:
        intent = create(
            "", EventType.MEETING, "Встреча", date=TOMORROW, time=time(15), duration_minutes=30
        )

        assert creation_draft(intent, NOW).ends_at == at(TOMORROW, 15, 30)

    def test_end_of_week_is_sunday_2359(self) -> None:
        intent = create("", EventType.TASK, "Билеты", date=SUNDAY, time=time(23, 59))

        assert creation_draft(intent, NOW).starts_at == at(SUNDAY, 23, 59)

    def test_task_next_week_is_due_sunday_of_that_week(self) -> None:
        draft = creation_draft(create("", EventType.TASK, "Ремонт", week_of=NEXT_MONDAY), NOW)

        assert (draft.starts_at, draft.has_time) == (at(date(2026, 11, 8), 23, 59), True)

    def test_task_with_date_only_has_no_time(self) -> None:
        draft = creation_draft(create("", EventType.TASK, "Отчёт", date=TOMORROW), NOW)

        assert (draft.starts_at, draft.has_time) == (at(TOMORROW, 0), False)

    def test_time_only_later_today(self) -> None:
        assert creation_draft(
            create("", EventType.REMINDER, "Чай", time=time(12, 5)), NOW
        ).starts_at == at(TODAY, 12, 5)

    def test_time_only_already_passed_means_tomorrow(self) -> None:
        assert creation_draft(
            create("", EventType.REMINDER, "Чай", time=time(12, 0)), NOW
        ).starts_at == at(TOMORROW, 12)

    def test_undated_task_has_no_start(self) -> None:
        draft = creation_draft(create("", EventType.TASK, "Хлеб"), NOW)

        assert (draft.starts_at, draft.has_time, draft.ends_at) == (None, False, None)


class TestMerging:
    def test_answer_fills_missing_time(self) -> None:
        merged = merge_when(When(date=TOMORROW), When(time=time(15)))

        assert merged == When(date=TOMORROW, time=time(15))

    def test_named_day_replaces_week(self) -> None:
        merged = merge_when(When(week_of=NEXT_MONDAY, time=time(15)), When(date=date(2026, 11, 4)))

        assert merged == When(date=date(2026, 11, 4), time=time(15))

    def test_title_answer_uses_whole_text_without_extracted_title(self) -> None:
        pending = create("", EventType.TASK, None)
        merged = merge_answer(
            pending, Intent(Action.ANSWER, "  купить подарок маме. "), PendingExpectation.TITLE
        )

        assert merged.title == "Купить подарок маме"
        assert merged.action is Action.CREATE

    def test_time_answer_keeps_title(self) -> None:
        pending = create("", EventType.MEETING, "Встреча с Иваном", date=TOMORROW)
        answer = Intent(Action.ANSWER, "в 15", when=When(time=time(15)))

        merged = merge_answer(pending, answer, PendingExpectation.TIME)

        assert (merged.title, merged.when) == (
            "Встреча с Иваном",
            When(date=TOMORROW, time=time(15)),
        )


class TestReschedule:
    @pytest.fixture
    def demo(self) -> EventCard:
        return card(EventType.MEETING, "Демо", at(TOMORROW, 10), ends_at=at(TOMORROW, 11))

    def test_time_only_keeps_day(self, demo: EventCard) -> None:
        schedule = rescheduled_schedule(demo, When(time=time(16)), NOW)

        assert (schedule.starts_at, schedule.has_time) == (at(TOMORROW, 16), True)

    def test_day_only_keeps_time(self, demo: EventCard) -> None:
        schedule = rescheduled_schedule(demo, When(date=SUNDAY), NOW)

        assert schedule.starts_at == at(SUNDAY, 10)

    def test_named_duration_sets_new_end(self, demo: EventCard) -> None:
        schedule = rescheduled_schedule(demo, When(time=time(17)), NOW, duration_minutes=30)

        assert (schedule.starts_at, schedule.ends_at) == (at(TOMORROW, 17), at(TOMORROW, 17, 30))

    def test_without_duration_end_is_left_to_editor(self, demo: EventCard) -> None:
        """Пустой `ends_at` — «не менять длительность»: редактор сдвинет конец с началом."""
        schedule = rescheduled_schedule(demo, When(time=time(17)), NOW)

        assert schedule.ends_at is None

    def test_duration_does_not_apply_to_task(self) -> None:
        task = card(EventType.TASK, "Отчёт", at(TOMORROW, 10))

        schedule = rescheduled_schedule(task, When(time=time(17)), NOW, duration_minutes=30)

        assert schedule.ends_at is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  купить   хлеб. ", "Купить хлеб"),
        ("«Отчёт Ольге»", "Отчёт Ольге"),
        ("   ", None),
        (None, None),
    ],
)
def test_tidy_title(raw: str | None, expected: str | None) -> None:
    assert tidy_title(raw) == expected
