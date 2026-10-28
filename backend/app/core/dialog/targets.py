"""На какую запись ссылается команда изменения: «её» — из контекста, иначе поиск."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from app.core.dialog.models import Turn
from app.core.dialog.relevance import asked_types, near_best
from app.core.enums import EventStatus, EventType
from app.core.errors import EventValidationError
from app.core.events import EventCard, EventService, ScoredCard
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW
from app.nlu.interfaces import Action, Intent, TargetRef, When

DAYS_PER_WEEK = 7
OPEN_ONLY_ACTIONS = frozenset({Action.RESCHEDULE, Action.COMPLETE})
"""Переносят и отмечают невыполненное; если такого нет — ищем среди всех записей."""
FOCUS_TIE_MARGIN = 0.015
"""Упомянутая в разговоре запись решает выбор, только если почти не уступает лидеру:
иначе только что созданная «Встреча с Иваном» перехватила бы «отметь звонок Ивану»."""


@dataclass(frozen=True, slots=True)
class TargetLookup:
    """Подходящие записи по убыванию уместности.

    `query` — что искали; `None` — команда ссылалась на запись из контекста («её»)
    или описала её только днём и временем — тогда они в `moment`.
    """

    candidates: Sequence[EventCard]
    query: str | None
    moment: When | None = None


class TargetFinder:
    """Находит записи, к которым относится команда изменения."""

    def __init__(self, reader: EventService) -> None:
        self._reader = reader

    async def find(self, turn: Turn, intent: Intent) -> TargetLookup:
        """`target.last` или пустая ссылка — запись из контекста; иначе — поиск по описанию.

        После ответа-списка («Что у меня сегодня?» → два напоминания) «её» неоднозначно:
        кандидаты — все записи того ответа (подходящего типа), и ассистент переспросит.
        Ссылка без описания, но с днём и временем («завтрашнюю встречу в 10») — записи
        названного типа в это время (`_at_moment`).
        """
        target = intent.target or TargetRef(last=True)
        if not target.last and not target.query and target.when is not None:
            at_moment = await self._at_moment(turn, intent.action, target, target.when)
            return TargetLookup(at_moment, query=None, moment=target.when)
        if target.last or not target.query:
            return TargetLookup(_referenced(turn, target), query=None)
        found = await self._search(turn, intent.action, target, target.query)
        return TargetLookup(_narrow(found, turn.focus), query=target.query)

    async def _search(
        self, turn: Turn, action: Action, target: TargetRef, query: str
    ) -> list[ScoredCard]:
        start, end = _day_bounds(target.when)
        criteria = EventFilter(
            profile_id=turn.profile_id,
            period_start=start,
            period_end=end,
            event_types=asked_types(target.event_type),
        )
        if action in OPEN_ONLY_ACTIONS:
            open_criteria = replace(criteria, status=EventStatus.OPEN)
            found = await self._search_with(open_criteria, query, target)
            if found:
                return found
        return await self._search_with(criteria, query, target)

    async def _search_with(
        self, criteria: EventFilter, query: str, target: TargetRef
    ) -> list[ScoredCard]:
        """Все подходящие записи, без предела выдачи.

        Варианты выбора — самые актуальные по времени (`router.CHOICE_LIMIT`): предел по
        оценке до этого выбора отрезал бы ближайшую из многих одинаковых записей.
        """
        found = await self._reader.search_scored(
            criteria, query, None, preferred_type=target.event_type
        )
        return _prefer_exact_time(found, target.when)

    async def _at_moment(
        self, turn: Turn, action: Action, target: TargetRef, when: When
    ) -> list[EventCard]:
        """Записи названного типа в названные день и время, по времени начала.

        Названо время — только записи ровно в это время, как и при поиске по описанию:
        другая запись того же дня не подменяет названную. Время без дня ищется с сегодняшнего
        дня: «перенеси встречу в 15» — о ближайшей, а не о встрече годичной давности.
        """
        start, end = _day_bounds(when)
        if start is None:
            start = _midnight(turn.today)
        criteria = EventFilter(
            profile_id=turn.profile_id,
            period_start=start,
            period_end=end,
            event_types=asked_types(target.event_type),
        )
        if action in OPEN_ONLY_ACTIONS:
            open_criteria = replace(criteria, status=EventStatus.OPEN)
            found = await self._list_at(open_criteria, when)
            if found:
                return found
        return await self._list_at(criteria, when)

    async def _list_at(self, criteria: EventFilter, when: When) -> list[EventCard]:
        cards = await self._reader.list_events(criteria, TARGET_SEARCH_LIMIT)
        if when.time is None:
            return cards
        return [card for card in cards if _starts_exactly_at(card, when.time)]


def _referenced(turn: Turn, target: TargetRef) -> tuple[EventCard, ...]:
    """На что указывает «её / эту встречу»: записи ответа-списка или одна запись фокуса."""
    if turn.peers:
        return tuple(_matching(turn.peers, target))
    card = _from_focus(_matching(turn.focus, target), target.event_type)
    return () if card is None else (card,)


def _matching(cards: Sequence[EventCard], target: TargetRef) -> list[EventCard]:
    """Явные ограничения действуют и для записей из контекста."""
    start, end = _day_bounds(target.when)
    typed = _of_type(cards, target.event_type)
    return [
        card
        for card in typed
        if (start is None or (card.starts_at is not None and start <= card.starts_at))
        and (end is None or (card.starts_at is not None and card.starts_at < end))
        and (target.when is None or target.when.time is None
             or _starts_exactly_at(card, target.when.time))
    ]


def _of_type(cards: Sequence[EventCard], event_type: EventType | None) -> list[EventCard]:
    types = asked_types(event_type)
    return [card for card in cards if types is None or card.type in types]


def _from_focus(focus: Sequence[EventCard], event_type: EventType | None) -> EventCard | None:
    """Первая запись в фокусе; если назван тип («перенеси встречу») — первая такого типа."""
    typed = _of_type(focus, event_type)
    if typed:
        return typed[0]
    return None  # if !focus - перейти в уточнение


def _day_bounds(when: When | None) -> tuple[datetime | None, datetime | None]:
    """Период, в котором стоит запись: названный день или неделя; иначе без ограничения."""
    if when is None:
        return None, None
    if when.date is not None:
        return _midnight(when.date), _period_end(when.date, 1)
    if when.week_of is not None:
        return _midnight(when.week_of), _period_end(when.week_of, DAYS_PER_WEEK)
    return None, None


def _period_end(day: date, days: int) -> datetime:
    try:
        return _midnight(day + timedelta(days=days))
    except OverflowError as error:
        raise EventValidationError("Дата выходит за допустимый диапазон.") from error


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=MOSCOW)


def _prefer_exact_time(found: list[ScoredCard], when: When | None) -> list[ScoredCard]:
    """Если названо время («созвон в 15»), записи ровно в это время — единственные кандидаты."""
    if when is None or when.time is None:
        return found
    exact = [item for item in found if _starts_exactly_at(item.card, when.time)]
    return exact  # изменить на строгий ( if (exact) ? return exact : exeption - не найдено)


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
