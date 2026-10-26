"""Выбор записи для команды изменения: лидер, равные кандидаты, недавно упомянутая запись."""

from datetime import UTC, datetime

from app.core.dialog.relevance import SCORE_MARGIN
from app.core.dialog.targets import _narrow
from app.core.enums import EventSource, EventStatus, EventType
from app.core.events import EventCard, ScoredCard

MOMENT = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def card(event_id: int, title: str) -> EventCard:
    return EventCard(
        id=event_id,
        type=EventType.TASK,
        title=title,
        starts_at=MOMENT,
        has_time=True,
        ends_at=None,
        status=EventStatus.OPEN,
        source=EventSource.USER,
        created_at=MOMENT,
        updated_at=MOMENT,
    )


CALL = card(1, "Позвонить Ивану")
BUDGET = card(2, "Обсудить бюджет с Иваном")
CALL_AGAIN = card(3, "Позвонить Ивану")


def test_candidates_far_behind_the_leader_are_dropped() -> None:
    found = [ScoredCard(CALL, 0.80), ScoredCard(BUDGET, 0.80 - SCORE_MARGIN - 0.01)]

    assert _narrow(found, focus=()) == [CALL]


def test_equal_candidates_stay_for_choice() -> None:
    found = [ScoredCard(CALL, 0.80), ScoredCard(CALL_AGAIN, 0.80), ScoredCard(BUDGET, 0.50)]

    assert _narrow(found, focus=()) == [CALL, CALL_AGAIN]


def test_recently_mentioned_record_wins_among_close_candidates() -> None:
    found = [ScoredCard(CALL_AGAIN, 0.80), ScoredCard(CALL, 0.79)]

    assert _narrow(found, focus=(CALL,)) == [CALL]


def test_mentioned_record_noticeably_behind_does_not_take_over() -> None:
    meeting = card(4, "Встреча с Иваном")
    found = [ScoredCard(CALL, 0.80), ScoredCard(meeting, 0.76)]

    assert _narrow(found, focus=(meeting,)) == [CALL, meeting]


def test_mentioned_record_far_behind_does_not_win() -> None:
    found = [ScoredCard(CALL, 0.80), ScoredCard(BUDGET, 0.50)]

    assert _narrow(found, focus=(BUDGET,)) == [CALL]


def test_nothing_found_stays_empty() -> None:
    assert _narrow([], focus=(CALL,)) == []
