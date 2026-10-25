"""Задачи, напоминания и встречи: создание, изменение, удаление, выборка и поиск.

Все сценарии работают только с записями одного профиля: чужая запись неотличима
от отсутствующей. Название при создании и изменении сразу индексируется для поиска.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import partial
from typing import Literal, Self
from uuid import UUID

from app.core.enums import EventSource, EventStatus, EventType
from app.core.errors import EventNotFoundError, EventValidationError
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW, Schedule, settle_schedule
from app.core.search import SearchService
from app.storage.database import UnitOfWork
from app.storage.models import EventRecord

PERIOD_ORDER_MESSAGE = "Начало периода должно быть раньше его конца."


class Keep(Enum):
    """Значение поля при изменении записи: «оставить как есть»."""

    KEEP = "keep"


KEEP = Keep.KEEP


@dataclass(frozen=True, slots=True)
class EventCard:
    """Запись для показа пользователю; время — по Москве."""

    id: int
    type: EventType
    title: str
    starts_at: datetime | None
    has_time: bool
    ends_at: datetime | None
    status: EventStatus
    source: EventSource
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: EventRecord) -> Self:
        """Карточка из строки таблицы `events`."""
        return cls(
            id=record.id,
            type=record.type,
            title=record.title,
            starts_at=_in_moscow(record.starts_at),
            has_time=record.has_time,
            ends_at=_in_moscow(record.ends_at),
            status=record.status,
            source=record.source,
            created_at=record.created_at.astimezone(MOSCOW),
            updated_at=record.updated_at.astimezone(MOSCOW),
        )


@dataclass(frozen=True, slots=True)
class EventDraft:
    """Новая запись от пользователя."""

    type: EventType
    title: str
    starts_at: datetime | None = None
    has_time: bool = True
    ends_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventChanges:
    """Изменения записи. `None` у названия, `has_time` и статуса — «не менять»;
    у `starts_at` и `ends_at` «не менять» — это `KEEP`, а `None` стирает значение."""

    title: str | None = None
    starts_at: datetime | Literal[Keep.KEEP] | None = KEEP
    has_time: bool | None = None
    ends_at: datetime | Literal[Keep.KEEP] | None = KEEP
    status: EventStatus | None = None


class EventService:
    """Сценарии работы с записями профиля. Изменяющий сценарий — одна транзакция."""

    def __init__(self, storage: UnitOfWork, search: SearchService) -> None:
        self._storage = storage
        self._search = search

    async def create(self, profile_id: UUID, draft: EventDraft) -> EventCard:
        """Создаёт запись.

        Raises:
            EventValidationError: Время не подходит к типу записи (см. `settle_schedule`).
        """
        schedule = settle_schedule(
            draft.type, Schedule(draft.starts_at, draft.has_time, draft.ends_at)
        )
        index = await self._search.index_title(draft.title)
        record = EventRecord(
            profile_id=profile_id,
            type=draft.type,
            title=draft.title,
            starts_at=schedule.starts_at,
            has_time=schedule.has_time,
            ends_at=schedule.ends_at,
            embedding=index.embedding,
            lemmas=index.lemmas,
        )
        await self._storage.events.add(record)
        await self._storage.commit()
        return EventCard.from_record(record)

    async def update(self, profile_id: UUID, event_id: int, changes: EventChanges) -> EventCard:
        """Меняет запись профиля; новое название сразу индексируется для поиска.

        Raises:
            EventNotFoundError: У профиля нет такой записи.
            EventValidationError: Новое время не подходит к типу записи.
        """
        record = await self._owned_event(profile_id, event_id)
        schedule = settle_schedule(record.type, _changed_schedule(record, changes))
        record.starts_at, record.has_time, record.ends_at = (
            schedule.starts_at,
            schedule.has_time,
            schedule.ends_at,
        )
        if changes.title is not None and changes.title != record.title:
            await self._rename(record, changes.title)
        if changes.status is not None:
            record.status = changes.status
        await self._storage.commit()
        return EventCard.from_record(record)

    async def delete(self, profile_id: UUID, event_id: int) -> None:
        """Удаляет запись профиля.

        Raises:
            EventNotFoundError: У профиля нет такой записи.
        """
        if not await self._storage.events.delete(profile_id, event_id):
            raise EventNotFoundError()
        await self._storage.commit()

    async def list_events(self, criteria: EventFilter, limit: int) -> list[EventCard]:
        """Записи по критериям в порядке времени начала.

        Raises:
            EventValidationError: Начало периода не раньше его конца.
        """
        _check_period(criteria)
        records = await self._storage.events.list_matching(criteria, limit)
        return [EventCard.from_record(record) for record in records]

    async def search_events(self, criteria: EventFilter, query: str, limit: int) -> list[EventCard]:
        """Записи по критериям, похожие на запрос, по убыванию релевантности.

        Raises:
            EventValidationError: Начало периода не раньше его конца.
        """
        _check_period(criteria)
        find_candidates = partial(self._storage.events.find_candidates, criteria)
        ranked = await self._search.search(query, find_candidates, limit=limit)
        records = await self._storage.events.get_many(
            criteria.profile_id, [result.event_id for result in ranked]
        )
        return [EventCard.from_record(record) for record in records]

    async def _owned_event(self, profile_id: UUID, event_id: int) -> EventRecord:
        record = await self._storage.events.get(profile_id, event_id)
        if record is None:
            raise EventNotFoundError()
        return record

    async def _rename(self, record: EventRecord, title: str) -> None:
        index = await self._search.index_title(title)
        record.title = title
        record.embedding = index.embedding
        record.lemmas = index.lemmas


def _changed_schedule(record: EventRecord, changes: EventChanges) -> Schedule:
    """Время записи после изменений. Перенос встречи сохраняет её длительность."""
    starts_at = record.starts_at if changes.starts_at is KEEP else changes.starts_at
    has_time = record.has_time if changes.has_time is None else changes.has_time
    if changes.ends_at is not KEEP:
        ends_at = changes.ends_at
    elif record.ends_at is None or record.starts_at is None or starts_at is None:
        ends_at = None
    else:
        ends_at = record.ends_at + (starts_at - record.starts_at)
    return Schedule(starts_at=starts_at, has_time=has_time, ends_at=ends_at)


def _check_period(criteria: EventFilter) -> None:
    if criteria.period_start is None or criteria.period_end is None:
        return
    if criteria.period_start >= criteria.period_end:
        raise EventValidationError(PERIOD_ORDER_MESSAGE)


def _in_moscow(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(MOSCOW)
