"""Вопросы о записях: список за период и поиск по смыслу.

Список: «Что у меня сегодня?», «Какие задачи на завтра?» — период из разбора, по
умолчанию сегодня; «задачи» — это задачи и напоминания (`relevance.ASKED_TYPES`).
Поиск: «Найди задачу про презентацию», «Когда у меня была встреча с Иваном?». Для «когда
была / когда будет» кандидаты — все записи с оценкой рядом с лучшей (близкие названия
почти равны), среди них — последняя прошедшая или ближайшая будущая. Поиск отдаёт все
подходящие записи, а предел — только у показанного: иначе среди 60 одинаковых встреч
ближайшая могла бы не дожить до выбора по времени.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import itemgetter
from types import MappingProxyType
from typing import Final

from app.core.dialog import phrases
from app.core.dialog.models import Outcome, Reply, Turn
from app.core.dialog.relevance import (
    WHEN_SCORE_MARGIN,
    asked_types,
    by_score_then_timeliness,
    near_best,
)
from app.core.enums import EventType, ReplyKind
from app.core.events import EventCard, EventService, ScoredCard
from app.core.queries import EventFilter
from app.core.schedule import start_of_day
from app.nlu.interfaces import Intent, Period, TimeScope

LIST_LIMIT = 100
MANY_FOUND = 50
"""С какого числа найденных говорить «много похожих» вместо точного числа."""
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
        today = today_period(turn.now)

        include_undated = (
            period.start == today.start
            and period.end == today.end
            and intent.event_type in (None, EventType.TASK)
        )

        criteria = EventFilter(
            profile_id=turn.profile_id,
            period_start=period.start,
            period_end=period.end,
            event_types=asked_types(intent.event_type),
            status=intent.status,
            include_undated=include_undated,
        )

        events = await self._reader.list_events(criteria, LIST_LIMIT)
        text = phrases.list_summary(events, period, turn.now, intent.event_type)
        reply = Reply(ReplyKind.LIST, text, events=events, period=period)

        return Outcome(
            reply,
            focus=tuple(card.id for card in events),
            peer_focus=True,
        )


@dataclass(frozen=True, slots=True)
class _Answer:
    """Главная запись выдачи и текст про неё."""

    chosen: EventCard
    text: str


@dataclass(frozen=True, slots=True)
class _Found:
    """Выдача поиска по убыванию оценки (равные — ближайшая будущая первой) и вопрос."""

    ranked: Sequence[ScoredCard]
    asked_type: EventType | None

    @property
    def best(self) -> EventCard:
        return self.ranked[0].card

    def contenders(self) -> list[EventCard]:
        """Равноправные кандидаты ответа «когда»: оценка рядом с лучшей, тип — названный."""
        near = [item.card for item in near_best(self.ranked, WHEN_SCORE_MARGIN)]
        types = asked_types(self.asked_type)
        typed = [card for card in near if types is None or card.type in types]
        return typed or near


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
        scored = await self._reader.search_scored(
            criteria, query, None, preferred_type=intent.event_type
        )
        if not scored:
            return Outcome.say(phrases.SEARCH_NOTHING)
        found = _Found(by_score_then_timeliness(scored, turn.now), intent.event_type)
        answer = _ANSWERS[intent.time_scope](found, turn)
        others = (item.card for item in found.ranked if item.card.id != answer.chosen.id)
        events = [answer.chosen, *others][:REPLY_EVENTS_LIMIT]
        reply = Reply(ReplyKind.SEARCH_RESULTS, answer.text, events=events)
        # «Когда была / будет…» называет одну запись — «её» после такого ответа однозначно.
        names_one = intent.time_scope is not TimeScope.ANY
        return Outcome(reply, focus=tuple(card.id for card in events), peer_focus=not names_one)


def _split_by_now(
    cards: Sequence[EventCard], now: datetime
) -> tuple[list[EventCard], list[EventCard]]:
    """Записи с датой: прошедшие и будущие, каждые по возрастанию времени."""
    dated = sorted(
        ((card.starts_at, card) for card in cards if card.starts_at is not None),
        key=itemgetter(0),
    )
    past = [card for moment, card in dated if moment < now]
    future = [card for moment, card in dated if moment >= now]
    return past, future


def _latest_past_first(found: _Found, turn: Turn) -> _Answer:
    """«Когда была…»: последняя прошедшая; если прошедших нет — честно и ближайшая будущая."""
    past, future = _split_by_now(found.contenders(), turn.now)
    if past:
        return _Answer(past[-1], phrases.search_latest_past(past[-1], turn.today))
    if future:
        return _Answer(future[0], phrases.search_no_past(future[0], turn.today))
    return _Answer(found.best, phrases.search_undated(found.best))


def _nearest_future_first(found: _Found, turn: Turn) -> _Answer:
    """«Когда будет…»: ближайшая будущая; если будущих нет — честно и последняя прошедшая."""
    past, future = _split_by_now(found.contenders(), turn.now)
    if future:
        return _Answer(future[0], phrases.search_nearest_future(future[0], turn.today))
    if past:
        return _Answer(past[-1], phrases.search_no_future(past[-1], turn.today))
    return _Answer(found.best, phrases.search_undated(found.best))


def _best_match_first(found: _Found, turn: Turn) -> _Answer:
    """«Найди…»: самая подходящая запись и сколько всего нашлось."""
    total = len(found.ranked)
    text = phrases.search_found(total, found.best, turn.today, capped=total >= MANY_FOUND)
    return _Answer(found.best, text)


_ANSWERS: Final[Mapping[TimeScope, Callable[[_Found, Turn], _Answer]]] = MappingProxyType(
    {
        TimeScope.PAST: _latest_past_first,
        TimeScope.FUTURE: _nearest_future_first,
        TimeScope.ANY: _best_match_first,
    }
)
