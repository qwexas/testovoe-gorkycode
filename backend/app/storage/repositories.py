"""Репозитории: запросы к таблицам. Транзакцией управляет `UnitOfWork`."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Uuid,
    case,
    delete,
    func,
    insert,
    inspect,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EventSource, EventStatus, EventType
from app.core.queries import EventFilter, MeetingSlot
from app.core.schedule import DEFAULT_MEETING_DURATION
from app.search.interfaces import SearchCandidate
from app.storage.models import (
    ChatMessageRecord,
    DialogStateRecord,
    EventRecord,
    ProfileRecord,
    ProfileSessionRecord,
    SeedEventRecord,
    UndoActionRecord,
)

NEAREST_CANDIDATES = 100
"""Сколько ближайших по вектору записей отдавать в ранжирование (плюс совпавшие по леммам)."""

SEED_LOCK_KEY = 0x676F726B79
"""Ключ advisory-блокировки заполнения `seed_events`: два процесса не заполняют её дважды."""

_COPIED_COLUMNS = ("type", "title", "starts_at", "has_time", "ends_at")
"""Поля записи истории, которые получает профиль; поисковый индекс остаётся в заготовке."""

_SEED_COLUMNS = tuple(attribute.key for attribute in inspect(SeedEventRecord).column_attrs)

_INDEXED_EMBEDDING = func.coalesce(EventRecord.embedding, SeedEventRecord.embedding)
_INDEXED_LEMMAS = func.coalesce(EventRecord.lemmas, SeedEventRecord.lemmas)
"""Индекс записи: собственный, а у нетронутой записи истории — из `seed_events`."""


class ProfileRepository:
    """Профили и их сессии."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, recovery_code_digest: str, calendar_token: str) -> ProfileRecord:
        """Создаёт профиль и возвращает его с заполненными `id` и `created_at`."""
        profile = ProfileRecord(
            recovery_code_digest=recovery_code_digest,
            calendar_token=calendar_token,
        )
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    async def get_by_session(self, token_digest: str) -> ProfileRecord | None:
        """Профиль, которому принадлежит сессия с данным отпечатком токена."""
        statement = (
            select(ProfileRecord)
            .join(ProfileSessionRecord, ProfileSessionRecord.profile_id == ProfileRecord.id)
            .where(ProfileSessionRecord.token_digest == token_digest)
        )
        return await self._session.scalar(statement)

    async def get_by_recovery_code(self, recovery_code_digest: str) -> ProfileRecord | None:
        """Профиль по отпечатку кода восстановления."""
        statement = select(ProfileRecord).where(
            ProfileRecord.recovery_code_digest == recovery_code_digest
        )
        return await self._session.scalar(statement)

    async def get_by_calendar_token(self, calendar_token: str) -> ProfileRecord | None:
        """Профиль по секретному токену подписки на календарь."""
        statement = select(ProfileRecord).where(ProfileRecord.calendar_token == calendar_token)
        return await self._session.scalar(statement)

    async def add_session(self, profile_id: UUID, token_digest: str) -> None:
        """Привязывает новую сессию устройства к профилю."""
        self._session.add(ProfileSessionRecord(token_digest=token_digest, profile_id=profile_id))
        await self._session.flush()

    async def delete_session(self, token_digest: str) -> None:
        """Удаляет сессию устройства, если она есть."""
        await self._session.execute(
            delete(ProfileSessionRecord).where(ProfileSessionRecord.token_digest == token_digest)
        )

    async def delete(self, profile_id: UUID) -> None:
        """Удаляет профиль; записи, диалог и сессии удаляются каскадом в базе."""
        await self._session.execute(delete(ProfileRecord).where(ProfileRecord.id == profile_id))


class EventRepository:
    """Задачи, напоминания и встречи профиля."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_for_profile(self, profile_id: UUID) -> int:
        """Количество записей профиля."""
        statement = (
            select(func.count())
            .select_from(EventRecord)
            .where(EventRecord.profile_id == profile_id)
        )
        return await self._session.scalar(statement) or 0

    async def add(self, event: EventRecord) -> None:
        """Сохраняет новую запись; `id` и даты создания заполняются сразу."""
        self._session.add(event)
        await self._session.flush()

    async def get(self, profile_id: UUID, event_id: int) -> EventRecord | None:
        """Запись профиля; чужая запись — как отсутствующая."""
        statement = select(EventRecord).where(
            EventRecord.id == event_id, EventRecord.profile_id == profile_id
        )
        return await self._session.scalar(statement)

    async def get_many(self, profile_id: UUID, event_ids: Sequence[int]) -> list[EventRecord]:
        """Записи профиля в порядке `event_ids`; чужие и удалённые пропускаются."""
        statement = select(EventRecord).where(
            EventRecord.profile_id == profile_id, EventRecord.id.in_(event_ids)
        )
        found = {event.id: event for event in await self._session.scalars(statement)}
        return [found[event_id] for event_id in event_ids if event_id in found]

    async def delete(self, profile_id: UUID, event_id: int) -> bool:
        """Удаляет запись профиля; `False`, если такой записи у профиля нет."""
        statement = (
            delete(EventRecord)
            .where(EventRecord.id == event_id, EventRecord.profile_id == profile_id)
            .returning(EventRecord.id)
        )
        return await self._session.scalar(statement) is not None

    async def list_matching(self, criteria: EventFilter, limit: int) -> list[EventRecord]:
        """Записи по критериям: по времени начала, записи без даты — в конце."""
        statement = (
            select(EventRecord)
            .where(*_filter_conditions(criteria))
            .order_by(EventRecord.starts_at.asc().nulls_last(), EventRecord.id)
            .limit(limit)
        )
        return list(await self._session.scalars(statement))

    async def find_candidates(
        self, criteria: EventFilter, query_vector: Sequence[float], query_lemmas: Sequence[str]
    ) -> list[SearchCandidate]:
        """Кандидаты поиска среди записей по критериям.

        Это `NEAREST_CANDIDATES` ближайших по косинусной близости плюс все записи,
        у которых есть общая лемма с запросом. Близость считается для каждого кандидата.
        """
        conditions = _filter_conditions(criteria)
        distance = _INDEXED_EMBEDDING.cosine_distance(list(query_vector))
        nearest = (
            _with_seed_index(select(EventRecord.id))
            .where(*conditions, _INDEXED_EMBEDDING.is_not(None))
            .order_by(distance)
            .limit(NEAREST_CANDIDATES)
        )
        is_candidate: ColumnElement[bool] = EventRecord.id.in_(nearest)
        if query_lemmas:
            is_candidate = or_(is_candidate, _INDEXED_LEMMAS.overlap(list(query_lemmas)))
        statement = _with_seed_index(
            select(
                EventRecord.id,
                EventRecord.type,
                _INDEXED_LEMMAS.label("lemmas"),
                (1 - distance).label("similarity"),
            )
        ).where(*conditions, is_candidate)
        rows = await self._session.execute(statement)
        return [
            SearchCandidate(
                event_id=row.id,
                lemmas=row.lemmas or [],
                similarity=row.similarity or 0.0,
                event_type=row.type,
            )
            for row in rows
        ]

    async def find_overlapping_meetings(self, slot: MeetingSlot) -> list[EventRecord]:
        """Открытые встречи профиля, пересекающиеся со `slot`, по времени начала.

        Встреча без конца считается длящейся `DEFAULT_MEETING_DURATION`.
        """
        meeting_end = func.coalesce(
            EventRecord.ends_at, EventRecord.starts_at + DEFAULT_MEETING_DURATION
        )
        conditions = [
            EventRecord.profile_id == slot.profile_id,
            EventRecord.type == EventType.MEETING,
            EventRecord.status == EventStatus.OPEN,
            EventRecord.starts_at < slot.ends_at,
            meeting_end > slot.starts_at,
        ]
        if slot.ignored_event_id is not None:
            conditions.append(EventRecord.id != slot.ignored_event_id)
        statement = select(EventRecord).where(*conditions).order_by(EventRecord.starts_at)
        return list(await self._session.scalars(statement))


class ChatMessageRepository:
    """История диалога профиля."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: ChatMessageRecord) -> None:
        """Сохраняет реплику; `id` и `created_at` заполняются сразу."""
        self._session.add(message)
        await self._session.flush()

    async def list_before(
        self, profile_id: UUID, before_id: int | None, limit: int
    ) -> list[ChatMessageRecord]:
        """Последние `limit` реплик профиля (с `id < before_id`, если задан), старые первыми."""
        statement = select(ChatMessageRecord).where(ChatMessageRecord.profile_id == profile_id)
        if before_id is not None:
            statement = statement.where(ChatMessageRecord.id < before_id)
        newest_first = await self._session.scalars(
            statement.order_by(ChatMessageRecord.id.desc()).limit(limit)
        )
        return list(reversed(newest_first.all()))


class DialogStateRepository:
    """Состояние диалога профиля: одна строка на профиль."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: UUID) -> DialogStateRecord | None:
        """Состояние диалога или `None`, если профиль ещё не разговаривал."""
        return await self._session.get(DialogStateRecord, profile_id, populate_existing=True)

    async def save(self, state: DialogStateRecord) -> None:
        """Записывает состояние поверх прежнего (`INSERT … ON CONFLICT DO UPDATE`)."""
        values = {
            "pending": state.pending,
            "last_event_ids": state.last_event_ids,
            "recent": state.recent,
        }
        statement = upsert(DialogStateRecord).values(profile_id=state.profile_id, **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[DialogStateRecord.profile_id],
                set_={**values, "updated_at": func.now()},
            )
        )


class UndoActionRepository:
    """Действия профиля, которые ещё можно отменить."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, action: UndoActionRecord) -> None:
        """Сохраняет действие."""
        self._session.add(action)
        await self._session.flush()

    async def get(self, profile_id: UUID, action_id: str) -> UndoActionRecord | None:
        """Действие профиля; чужое — как отсутствующее."""
        statement = select(UndoActionRecord).where(
            UndoActionRecord.action_id == action_id, UndoActionRecord.profile_id == profile_id
        )
        return await self._session.scalar(statement)

    async def latest(self, profile_id: UUID) -> UndoActionRecord | None:
        """Последнее действие профиля (с самым поздним сроком отмены)."""
        statement = (
            select(UndoActionRecord)
            .where(UndoActionRecord.profile_id == profile_id)
            .order_by(UndoActionRecord.expires_at.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

    async def delete(self, profile_id: UUID, action_id: str) -> None:
        """Удаляет действие: отменить его второй раз нельзя."""
        await self._session.execute(
            delete(UndoActionRecord).where(
                UndoActionRecord.action_id == action_id, UndoActionRecord.profile_id == profile_id
            )
        )

    async def delete_expired(self, profile_id: UUID, moment: datetime) -> None:
        """Удаляет действия профиля, срок отмены которых прошёл к `moment`."""
        await self._session.execute(
            delete(UndoActionRecord).where(
                UndoActionRecord.profile_id == profile_id, UndoActionRecord.expires_at <= moment
            )
        )


class SeedEventRepository:
    """Общая заготовка истории из CSV (`seed_events`)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self) -> None:
        """Блокирует заполнение заготовки до конца транзакции (advisory lock)."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK_KEY}
        )

    async def count(self) -> int:
        """Количество записей заготовки."""
        return await self._session.scalar(select(func.count()).select_from(SeedEventRecord)) or 0

    async def get(self, seed_id: int) -> SeedEventRecord | None:
        """Запись заготовки по номеру строки CSV."""
        return await self._session.get(SeedEventRecord, seed_id)

    async def save_all(self, records: Sequence[SeedEventRecord]) -> None:
        """Записывает заготовку поверх прежней, сохраняя ссылки профилей на её строки.

        Строки обновляются на месте по `id` (`INSERT … ON CONFLICT`), а строки, которых
        больше нет в `records`, удаляются: у записей профилей ссылка на них обнуляется.
        """
        rows = [{column: getattr(record, column) for column in _SEED_COLUMNS} for record in records]
        statement = upsert(SeedEventRecord)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[SeedEventRecord.id],
                set_={column: statement.excluded[column] for column in _SEED_COLUMNS},
            ),
            rows,
        )
        await self._session.execute(
            delete(SeedEventRecord).where(
                SeedEventRecord.id.not_in([record.id for record in records])
            )
        )

    async def copy_to_profile(self, profile_id: UUID) -> None:
        """Даёт профилю записи истории одним `INSERT … SELECT`.

        Копируются только поля записи и ссылка на заготовку. Статус — «выполнено»,
        если запись раньше момента создания профиля, иначе «открыта»; источник — импорт.
        """
        profile_created_at = (
            select(ProfileRecord.created_at).where(ProfileRecord.id == profile_id).scalar_subquery()
        )
        status = case(
            (SeedEventRecord.starts_at < profile_created_at, EventStatus.DONE.value),
            else_=EventStatus.OPEN.value,
        )
        history = select(
            literal(profile_id, Uuid),
            status,
            literal(EventSource.IMPORT.value),
            SeedEventRecord.id,
            *(getattr(SeedEventRecord, column) for column in _COPIED_COLUMNS),
        ).order_by(SeedEventRecord.id)
        await self._session.execute(
            insert(EventRecord).from_select(
                ["profile_id", "status", "source", "seed_event_id", *_COPIED_COLUMNS], history
            )
        )


def _with_seed_index[Statement: Select[Any]](statement: Statement) -> Statement:
    """Присоединяет заготовку истории, из которой записи без своего индекса берут его."""
    return statement.outerjoin(SeedEventRecord, EventRecord.seed_event_id == SeedEventRecord.id)


def _filter_conditions(criteria: EventFilter) -> list[ColumnElement[bool]]:
    conditions = [EventRecord.profile_id == criteria.profile_id]
    if criteria.period_start is not None:
        conditions.append(EventRecord.starts_at >= criteria.period_start)
    if criteria.period_end is not None:
        conditions.append(EventRecord.starts_at < criteria.period_end)
    if criteria.event_types is not None:
        conditions.append(EventRecord.type.in_(criteria.event_types))
    if criteria.status is not None:
        conditions.append(EventRecord.status == criteria.status)
    return conditions
