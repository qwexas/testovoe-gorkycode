"""Вопросы о записях: список за период и поиск по смыслу.

Список: «Что у меня сегодня?», «Какие задачи на завтра?» — период из разбора, по
умолчанию сегодня. Поиск: «Найди задачу про презентацию», «Когда у меня была встреча
с Иваном?» — выдача группируется по названию, и в первой группе выбирается последняя
прошедшая (`past`) или ближайшая будущая (`future`) запись (`docs/search.md`).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import itemgetter
from types import MappingProxyType
from typing import Final

from app.core.dialog import phrases
from app.core.dialog.models import Outcome, Reply, Turn
from app.core.enums import ReplyKind
from app.core.events import EventCard, EventService
from app.core.queries import EventFilter
from app.core.schedule import start_of_day
from app.nlu.interfaces import Intent, Period, TimeScope

LIST_LIMIT = 100
SEARCH_LIMIT = 50
"""Сколько записей просить у поиска, чтобы повторы одного названия не вытеснили остальные."""
REPLY_EVENTS_LIMIT = 10
TODAY_LABEL = "сегодня"


def today_period(now: datetime) -> Period:
    """Период по умолчанию для «что у меня?» — сегодняшний день по Москве."""
    start = start_of_day(now)
    return Period(start=start, end=start + timedelta(days=1), label=TODAY_LABEL)


class ListingFlow:
    """Записи за период с текстовой сводкой."""

    def __init__(self, reader: EventService) -> None:
        self._reader = reader

    async def run(self, turn: Turn, intent: Intent) -> Outcome:
        """Сводка и записи за период из разбора (по умолчанию — сегодня)."""
        period = intent.period or today_period(turn.now)
        criteria = EventFilter(
            profile_id=turn.profile_id,
            period_start=period.start,
            period_end=period.end,
            event_type=intent.event_type,
            status=intent.status,
        )
        events = await self._reader.list_events(criteria, LIST_LIMIT)
        text = phrases.list_summary(events, period, turn.now, intent.event_type)
        reply = Reply(ReplyKind.LIST, text, events=events, period=period)
        return Outcome(reply, focus=tuple(card.id for card in events))


@dataclass(frozen=True, slots=True)
class _Answer:
    """Главная запись выдачи и текст про неё."""

    chosen: EventCard
    text: str


class SearchFlow:
    """Поиск записей по смыслу с ответом на «когда было / когда будет»."""

    def __init__(self, reader: EventService) -> None:
        self._reader = reader

    async def run(self, turn: Turn, intent: Intent) -> Outcome:
        """Найденные записи; первой — та, о которой ответ."""
        criteria = EventFilter(
            profile_id=turn.profile_id,
            period_start=None if intent.period is None else intent.period.start,
            period_end=None if intent.period is None else intent.period.end,
            status=intent.status,
        )
        query = intent.query or intent.title or intent.text
        found = await self._reader.search_events(
            criteria, query, SEARCH_LIMIT, preferred_type=intent.event_type
        )
        if not found:
            return Outcome.say(phrases.SEARCH_NOTHING)
        answer = _ANSWERS[intent.time_scope](found, turn)
        events = [answer.chosen, *(card for card in found if card.id != answer.chosen.id)]
        reply = Reply(ReplyKind.SEARCH_RESULTS, answer.text, events=events[:REPLY_EVENTS_LIMIT])
        return Outcome(reply, focus=tuple(card.id for card in events[:REPLY_EVENTS_LIMIT]))


def _first_group(found: Sequence[EventCard]) -> list[EventCard]:
    """Записи с тем же названием, что и самая похожая (повторы одного дела)."""
    title = found[0].title.casefold()
    return [card for card in found if card.title.casefold() == title]


def _split_by_now(
    cards: Sequence[EventCard], now: datetime
) -> tuple[list[EventCard], list[EventCard]]:
    """Записи с датой: прошедшие (по возрастанию) и будущие (по возрастанию)."""
    dated = sorted(
        ((card.starts_at, card) for card in cards if card.starts_at is not None),
        key=itemgetter(0),
    )
    past = [card for moment, card in dated if moment < now]
    future = [card for moment, card in dated if moment >= now]
    return past, future


def _latest_past_first(found: Sequence[EventCard], turn: Turn) -> _Answer:
    """«Когда была…»: последняя прошедшая; если прошедших нет — ближайшая будущая."""
    past, future = _split_by_now(_first_group(found), turn.now)
    if past:
        return _Answer(past[-1], phrases.search_latest_past(past[-1], turn.today))
    if future:
        return _Answer(future[0], phrases.search_no_past(future[0], turn.today))
    return _Answer(found[0], phrases.search_undated(found[0]))


def _nearest_future_first(found: Sequence[EventCard], turn: Turn) -> _Answer:
    """«Когда будет…»: ближайшая будущая; если будущих нет — последняя прошедшая."""
    past, future = _split_by_now(_first_group(found), turn.now)
    if future:
        return _Answer(future[0], phrases.search_nearest_future(future[0], turn.today))
    if past:
        return _Answer(past[-1], phrases.search_no_future(past[-1], turn.today))
    return _Answer(found[0], phrases.search_undated(found[0]))


def _best_match_first(found: Sequence[EventCard], turn: Turn) -> _Answer:
    """«Найди…»: самая похожая запись и сколько всего нашлось."""
    capped = len(found) >= SEARCH_LIMIT
    return _Answer(found[0], phrases.search_found(len(found), found[0], turn.today, capped=capped))


_ANSWERS: Final[Mapping[TimeScope, Callable[[Sequence[EventCard], Turn], _Answer]]] = (
    MappingProxyType(
        {
            TimeScope.PAST: _latest_past_first,
            TimeScope.FUTURE: _nearest_future_first,
            TimeScope.ANY: _best_match_first,
        }
    )
)
