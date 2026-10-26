"""На какую запись ссылается команда изменения: «её» — из контекста, иначе поиск."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from app.core.dialog.models import Turn
from app.core.dialog.relevance import near_best
from app.core.enums import EventStatus, EventType
from app.core.events import EventCard, EventService, ScoredCard
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW
from app.nlu.interfaces import Action, Intent, TargetRef, When

TARGET_SEARCH_LIMIT = 50
"""Сколько записей просить у поиска: повторы одного названия не должны вытеснить остальные."""
DAYS_PER_WEEK = 7
OPEN_ONLY_ACTIONS = frozenset({Action.RESCHEDULE, Action.COMPLETE})
"""Переносят и отмечают невыполненное; если такого нет — ищем среди всех записей."""
FOCUS_TIE_MARGIN = 0.015
"""Упомянутая в разговоре запись решает выбор, только если почти не уступает лидеру:
иначе только что созданная «Встреча с Иваном» перехватила бы «отметь звонок Ивану»."""


@dataclass(frozen=True, slots=True)
class TargetLookup:
    """Подходящие записи по убыванию уместности.

    `query` — что искали; `None` — команда ссылалась на запись из контекста («её»).
    """

    candidates: Sequence[EventCard]
    query: str | None


class TargetFinder:
    """Находит записи, к которым относится команда изменения."""

    def __init__(self, reader: EventService) -> None:
        self._reader = reader

    async def find(self, turn: Turn, intent: Intent) -> TargetLookup:
        """`target.last` или пустая ссылка — запись в фокусе; иначе — поиск по описанию."""
        target = intent.target or TargetRef(last=True)
        if target.last or not target.query:
            card = _from_focus(turn.focus, target.event_type)
            return TargetLookup(() if card is None else (card,), query=None)
        found = await self._search(turn, intent.action, target, target.query)
        exact = _prefer_exact_time(found, target.when)
        return TargetLookup(_narrow(exact, turn.focus), query=target.query)

    async def _search(
        self, turn: Turn, action: Action, target: TargetRef, query: str
    ) -> list[ScoredCard]:
        start, end = _day_bounds(target.when)
        criteria = EventFilter(profile_id=turn.profile_id, period_start=start, period_end=end)
        if action in OPEN_ONLY_ACTIONS:
            open_criteria = replace(criteria, status=EventStatus.OPEN)
            found = await self._search_with(open_criteria, query, target.event_type)
            if found:
                return found
        return await self._search_with(criteria, query, target.event_type)

    async def _search_with(
        self, criteria: EventFilter, query: str, event_type: EventType | None
    ) -> list[ScoredCard]:
        return await self._reader.search_scored(
            criteria, query, TARGET_SEARCH_LIMIT, preferred_type=event_type
        )


def _from_focus(focus: Sequence[EventCard], event_type: EventType | None) -> EventCard | None:
    """Первая запись в фокусе; если назван тип («перенеси встречу») — первая такого типа."""
    if event_type is not None:
        typed = next((card for card in focus if card.type is event_type), None)
        if typed is not None:
            return typed
    return focus[0] if focus else None


def _day_bounds(when: When | None) -> tuple[datetime | None, datetime | None]:
    """Период, в котором стоит запись: названный день или неделя; иначе без ограничения."""
    if when is None:
        return None, None
    if when.date is not None:
        return _midnight(when.date), _midnight(when.date + timedelta(days=1))
    if when.week_of is not None:
        return _midnight(when.week_of), _midnight(when.week_of + timedelta(days=DAYS_PER_WEEK))
    return None, None


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=MOSCOW)


def _prefer_exact_time(found: list[ScoredCard], when: When | None) -> list[ScoredCard]:
    """Если названо время («созвон в 15»), записи ровно в это время — единственные кандидаты."""
    if when is None or when.time is None:
        return found
    exact = [item for item in found if _starts_exactly_at(item.card, when.time)]
    return exact or found


def _starts_exactly_at(card: EventCard, moment: time) -> bool:
    return card.has_time and card.starts_at is not None and card.starts_at.time() == moment


def _narrow(found: Sequence[ScoredCard], focus: Sequence[EventCard]) -> list[EventCard]:
    """Оставляет только кандидатов рядом с лидером; упомянутая запись разрешает ничью.

    Пользователь только что создал «Позвонить Ивану» и говорит «отметь звонок Ивану» — без
    вопроса «какую?» отмечаем её. Но упоминание не перевешивает заметно более похожую
    запись. Равные по оценке записи (повторы одного названия в разные дни) остаются
    вариантами выбора; отстающие больше чем на `relevance.SCORE_MARGIN` — отсекаются:
    иначе рядом с «Позвонить Ивану» предлагалось бы «Обсудить бюджет с Иваном».
    """
    if not found:
        return []
    best = found[0].score
    focus_ids = {card.id for card in focus}
    tied_mentioned = [
        item.card
        for item in found
        if item.card.id in focus_ids and best - item.score <= FOCUS_TIE_MARGIN
    ]
    if tied_mentioned:
        return tied_mentioned[:1]
    return [item.card for item in near_best(found)]
