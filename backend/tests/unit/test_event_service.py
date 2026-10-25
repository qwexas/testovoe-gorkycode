"""Бизнес-логика записей на фейковом хранилище: без базы и без модели."""

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.enums import EventSource, EventStatus, EventType
from app.core.errors import EventNotFoundError, EventValidationError
from app.core.events import EventChanges, EventDraft, EventService
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW
from app.core.search import SearchService
from app.search.interfaces import SearchCandidate
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer, SimilarityRanker
from app.storage.models import EventRecord

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
TOMORROW_15 = datetime(2026, 10, 27, 15, 0, tzinfo=MOSCOW)
HOUR = timedelta(hours=1)


class FakeEventRepository:
    """Записи в памяти с той же изоляцией по профилю, что и настоящий репозиторий."""

    def __init__(self) -> None:
        self.records: dict[int, EventRecord] = {}
        self.searched_criteria: list[EventFilter] = []

    async def add(self, event: EventRecord) -> None:
        event.id = len(self.records) + 1
        event.status = event.status or EventStatus.OPEN
        event.source = event.source or EventSource.USER
        event.created_at = event.updated_at = NOW
        self.records[event.id] = event

    async def get(self, profile_id: UUID, event_id: int) -> EventRecord | None:
        event = self.records.get(event_id)
        return event if event is not None and event.profile_id == profile_id else None

    async def get_many(self, profile_id: UUID, event_ids: Sequence[int]) -> list[EventRecord]:
        found = [await self.get(profile_id, event_id) for event_id in event_ids]
        return [event for event in found if event is not None]

    async def delete(self, profile_id: UUID, event_id: int) -> bool:
        if await self.get(profile_id, event_id) is None:
            return False
        del self.records[event_id]
        return True

    async def list_matching(self, criteria: EventFilter, limit: int) -> list[EventRecord]:
        owned = [e for e in self.records.values() if e.profile_id == criteria.profile_id]
        return owned[:limit]

    async def find_candidates(
        self, criteria: EventFilter, query_vector: Sequence[float], query_lemmas: Sequence[str]
    ) -> list[SearchCandidate]:
        self.searched_criteria.append(criteria)
        return [
            SearchCandidate(
                event_id=event.id,
                lemmas=event.lemmas,
                similarity=math.fsum(
                    a * b for a, b in zip(query_vector, event.embedding or [], strict=True)
                ),
            )
            for event in await self.list_matching(criteria, len(self.records))
        ]


class FakeStorage:
    def __init__(self) -> None:
        self.events = FakeEventRepository()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def service(storage: FakeStorage) -> EventService:
    search = SearchService(HashingEmbedder(), LowercaseLemmatizer(), SimilarityRanker())
    fake_storage: Any = storage
    return EventService(fake_storage, search)


@pytest.fixture
def profile_id() -> UUID:
    return uuid4()


async def title_vector(title: str) -> list[float]:
    return await HashingEmbedder().embed_query(title)


class TestCreate:
    async def test_saves_title_index_and_commits(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        card = await service.create(profile_id, EventDraft(EventType.TASK, "Купить билеты"))

        record = storage.events.records[card.id]
        assert record.embedding == await title_vector("Купить билеты")
        assert record.lemmas == ["купить", "билеты"]
        assert storage.commits == 1
        assert card.status is EventStatus.OPEN
        assert card.created_at.utcoffset() == timedelta(hours=3)

    async def test_meeting_gets_default_end(self, service: EventService, profile_id: UUID) -> None:
        card = await service.create(
            profile_id, EventDraft(EventType.MEETING, "Встреча с командой", TOMORROW_15)
        )

        assert card.ends_at == TOMORROW_15 + HOUR

    async def test_invalid_draft_is_not_saved(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        with pytest.raises(EventValidationError):
            await service.create(profile_id, EventDraft(EventType.REMINDER, "Позвонить Ивану"))

        assert storage.events.records == {}
        assert storage.commits == 0


class TestUpdate:
    async def create_meeting(self, service: EventService, profile_id: UUID) -> int:
        draft = EventDraft(EventType.MEETING, "Встреча с дизайнером", TOMORROW_15)
        return (await service.create(profile_id, draft)).id

    async def test_new_title_is_indexed_again(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)

        card = await service.update(profile_id, event_id, EventChanges(title="Демо для заказчика"))

        record = storage.events.records[event_id]
        assert card.title == "Демо для заказчика"
        assert record.embedding == await title_vector("Демо для заказчика")
        assert record.lemmas == ["демо", "для", "заказчика"]

    async def test_same_title_keeps_index(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)
        embedding_before = storage.events.records[event_id].embedding

        await service.update(profile_id, event_id, EventChanges(title="Встреча с дизайнером"))

        assert storage.events.records[event_id].embedding is embedding_before

    async def test_status_done(self, service: EventService, profile_id: UUID) -> None:
        event_id = await self.create_meeting(service, profile_id)

        card = await service.update(profile_id, event_id, EventChanges(status=EventStatus.DONE))

        assert card.status is EventStatus.DONE
        assert card.starts_at == TOMORROW_15

    async def test_moved_meeting_keeps_duration(
        self, service: EventService, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)
        await service.update(profile_id, event_id, EventChanges(ends_at=TOMORROW_15 + 2 * HOUR))
        moved = EventChanges(starts_at=TOMORROW_15 + HOUR)

        card = await service.update(profile_id, event_id, moved)

        assert card.starts_at == TOMORROW_15 + HOUR
        assert card.ends_at == TOMORROW_15 + 3 * HOUR

    async def test_explicit_end_wins_over_shift(
        self, service: EventService, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)
        changes = EventChanges(starts_at=TOMORROW_15 + HOUR, ends_at=TOMORROW_15 + HOUR)

        card = await service.update(profile_id, event_id, changes)

        assert card.ends_at == TOMORROW_15 + HOUR

    async def test_task_due_date_can_be_cleared(
        self, service: EventService, profile_id: UUID
    ) -> None:
        task = await service.create(profile_id, EventDraft(EventType.TASK, "Отчёт", TOMORROW_15))

        card = await service.update(profile_id, task.id, EventChanges(starts_at=None))

        assert card.starts_at is None
        assert card.has_time is False

    async def test_meeting_cannot_lose_time(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)
        commits_before = storage.commits

        with pytest.raises(EventValidationError):
            await service.update(profile_id, event_id, EventChanges(has_time=False))

        assert storage.commits == commits_before

    async def test_other_profile_event_is_not_found(
        self, service: EventService, profile_id: UUID
    ) -> None:
        event_id = await self.create_meeting(service, profile_id)

        with pytest.raises(EventNotFoundError):
            await service.update(uuid4(), event_id, EventChanges(status=EventStatus.DONE))


class TestDelete:
    async def test_removes_own_event(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        card = await service.create(profile_id, EventDraft(EventType.TASK, "Купить билеты"))

        await service.delete(profile_id, card.id)

        assert storage.events.records == {}
        assert storage.commits == 2

    async def test_missing_event_is_not_found(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        card = await service.create(profile_id, EventDraft(EventType.TASK, "Купить билеты"))

        with pytest.raises(EventNotFoundError):
            await service.delete(uuid4(), card.id)

        assert card.id in storage.events.records


class TestListAndSearch:
    @pytest.mark.parametrize("gap", [timedelta(0), -HOUR])
    async def test_period_must_be_ordered(
        self, service: EventService, profile_id: UUID, gap: timedelta
    ) -> None:
        criteria = EventFilter(profile_id, period_start=TOMORROW_15, period_end=TOMORROW_15 + gap)

        with pytest.raises(EventValidationError, match="периода"):
            await service.list_events(criteria, limit=10)
        with pytest.raises(EventValidationError, match="периода"):
            await service.search_events(criteria, "отчёт", limit=10)

    async def test_search_orders_by_relevance_within_criteria(
        self, service: EventService, storage: FakeStorage, profile_id: UUID
    ) -> None:
        for title in ["Отправить отчёт", "Купить билеты", "Отчёт"]:
            await service.create(profile_id, EventDraft(EventType.TASK, title))
        criteria = EventFilter(profile_id, event_type=EventType.TASK)

        found = await service.search_events(criteria, "отчёт", limit=10)

        assert [card.title for card in found] == ["Отчёт", "Отправить отчёт"]
        assert storage.events.searched_criteria == [criteria]

    async def test_search_respects_limit(self, service: EventService, profile_id: UUID) -> None:
        for title in ["Отчёт", "Отправить отчёт"]:
            await service.create(profile_id, EventDraft(EventType.TASK, title))

        found = await service.search_events(EventFilter(profile_id), "отчёт", limit=1)

        assert [card.title for card in found] == ["Отчёт"]

    async def test_search_does_not_leak_other_profiles(
        self, service: EventService, profile_id: UUID
    ) -> None:
        await service.create(profile_id, EventDraft(EventType.TASK, "Отчёт"))

        found = await service.search_events(EventFilter(uuid4()), "отчёт", limit=10)

        assert found == []
