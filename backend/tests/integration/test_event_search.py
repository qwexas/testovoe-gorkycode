"""Поиск: кандидаты из Postgres (по вектору и по леммам) → ранжирование → записи."""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.enums import EventType
from app.core.events import EventDraft, EventService
from app.core.history_source import read_history_file
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW
from app.core.search import SearchService
from app.search.interfaces import RankedResult, SearchCandidate
from app.search.placeholders import HashingEmbedder
from app.storage.database import UnitOfWork
from app.storage.models import EventRecord
from app.storage.repositories import NEAREST_CANDIDATES

pytestmark = pytest.mark.integration

HISTORY = read_history_file()
WORD = re.compile(r"[а-яё]+")
STEM_LENGTH = 5
FILLER_LEMMA = "заполнитель"


def words(title: str) -> list[str]:
    return WORD.findall(title.lower())


async def search(client: httpx.AsyncClient, q: str, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/api/events", params={"q": q, "limit": "200", **params})
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["events"]
    return events


class TestSearchApiOnHistory:
    """Заглушки: `HashingEmbedder` + `SimilarityRanker` находят точное слово в любой записи."""

    async def test_finds_history_records_with_the_word(self, client: httpx.AsyncClient) -> None:
        expected = {entry.title for entry in HISTORY if "договор" in words(entry.title)}

        found = await search(client, "договор")

        assert expected
        assert {event["title"] for event in found} == expected
        word_counts = [len(words(event["title"])) for event in found]
        assert word_counts == sorted(word_counts), "короче название — ближе вектор к запросу"

    async def test_filters_apply_to_search(self, client: httpx.AsyncClient) -> None:
        period_start, period_end = "2025-01-01T00:00:00+03:00", "2027-01-01T00:00:00+03:00"
        expected = {
            entry.title
            for entry in HISTORY
            if entry.type is EventType.MEETING
            and "презентации" in words(entry.title)
            and period_start <= entry.starts_at.isoformat() < period_end
        }

        found = await search(
            client, "презентации", type="meeting", **{"from": period_start, "to": period_end}
        )

        assert expected
        assert {event["title"] for event in found} == expected
        assert {event["type"] for event in found} == {"meeting"}

    async def test_status_filter_applies_to_search(self, client: httpx.AsyncClient) -> None:
        profile_created_at = datetime.fromisoformat(
            (await client.get("/api/me")).json()["created_at"]
        )
        created = await client.post(
            "/api/events", json={"type": "task", "title": "Подписать договор"}
        )
        expected = {
            entry.title
            for entry in HISTORY
            if "договор" in words(entry.title) and entry.starts_at >= profile_created_at
        }

        found = await search(client, "договор", status="open")

        assert expected
        assert {event["title"] for event in found} == expected | {"Подписать договор"}
        assert created.json()["id"] in {event["id"] for event in found}
        assert {event["status"] for event in found} == {"open"}

    async def test_nothing_similar_is_empty(self, client: httpx.AsyncClient) -> None:
        assert await search(client, "абракадабра") == []

    async def test_blank_query_lists_by_time(self, client: httpx.AsyncClient) -> None:
        found = await search(client, "   ", limit="3")

        assert [event["title"] for event in found] == [entry.title for entry in HISTORY[:3]]


class StemLemmatizer:
    """Учебная «морфология»: первые пять букв слова — «договору» и «договор» совпадают."""

    def lemmas(self, text: str) -> list[str]:
        return list(dict.fromkeys(word[:STEM_LENGTH] for word in words(text)))


class LemmaOverlapRanker:
    """Ранжирует только по числу общих лемм с запросом."""

    def __init__(self) -> None:
        self.seen_candidates: list[SearchCandidate] = []
        self.preferred_types: list[EventType | None] = []

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        self.seen_candidates.extend(candidates)
        self.preferred_types.append(preferred_type)
        scored = [
            RankedResult(candidate.event_id, float(len(set(query_lemmas) & set(candidate.lemmas))))
            for candidate in candidates
        ]
        relevant = sorted((r for r in scored if r.score > 0), key=lambda r: -r.score)
        return relevant[:limit]


@pytest.fixture
def events(storage: UnitOfWork) -> EventService:
    search_service = SearchService(HashingEmbedder(), StemLemmatizer(), LemmaOverlapRanker())
    return EventService(storage, search_service)


async def add_vector_neighbours(storage: UnitOfWork, profile_id: UUID, query: str) -> None:
    """`NEAREST_CANDIDATES` записей с вектором, равным вектору запроса, но без его лемм."""
    query_vector = await HashingEmbedder().embed_query(query)
    for number in range(NEAREST_CANDIDATES):
        await storage.events.add(
            EventRecord(
                profile_id=profile_id,
                type=EventType.TASK,
                title=f"Заполнитель {number}",
                embedding=query_vector,
                lemmas=[FILLER_LEMMA],
            )
        )
    await storage.commit()


class TestLemmaChannel:
    """Запись с другой формой слова далека по вектору, но приходит по пересечению лемм."""

    async def create(
        self, events: EventService, profile_id: UUID, title: str, **fields: Any
    ) -> int:
        event_type = fields.pop("type", EventType.TASK)
        return (await events.create(profile_id, EventDraft(event_type, title, **fields))).id

    async def test_candidates_are_nearest_plus_lemma_matches(
        self, storage: UnitOfWork, events: EventService, bare_profile_id: UUID
    ) -> None:
        await add_vector_neighbours(storage, bare_profile_id, "договор")
        other_form = await self.create(events, bare_profile_id, "Обсудить бюджет по договору")
        plural = await self.create(events, bare_profile_id, "Проверить договоры")
        await self.create(events, bare_profile_id, "Купить билеты")
        query_vector = await HashingEmbedder().embed_query("договор")

        by_vector = await storage.events.find_candidates(
            EventFilter(bare_profile_id), query_vector, []
        )
        both = await storage.events.find_candidates(
            EventFilter(bare_profile_id), query_vector, StemLemmatizer().lemmas("договор")
        )

        assert len(by_vector) == NEAREST_CANDIDATES
        assert {c.event_id for c in by_vector}.isdisjoint({other_form, plural})
        lemma_only = {c.event_id: c for c in both if FILLER_LEMMA not in c.lemmas}
        assert set(lemma_only) == {other_form, plural}
        assert all(candidate.similarity < 0.2 for candidate in lemma_only.values())

    async def test_candidates_carry_type_and_ranker_gets_preferred_type(
        self, storage: UnitOfWork, bare_profile_id: UUID
    ) -> None:
        ranker = LemmaOverlapRanker()
        typed_events = EventService(
            storage, SearchService(HashingEmbedder(), StemLemmatizer(), ranker)
        )
        meeting = await self.create(
            typed_events,
            bare_profile_id,
            "Встреча с Иваном",
            type=EventType.MEETING,
            starts_at=datetime(2026, 10, 27, 15, 0, tzinfo=MOSCOW),
        )
        task = await self.create(typed_events, bare_profile_id, "Итоги встречи с Иваном")

        await typed_events.search_events(
            EventFilter(bare_profile_id), "встреча Иван", 10, preferred_type=EventType.MEETING
        )

        assert ranker.preferred_types == [EventType.MEETING]
        types = {c.event_id: c.event_type for c in ranker.seen_candidates}
        assert types == {meeting: EventType.MEETING, task: EventType.TASK}

    async def test_any_word_form_is_found(
        self, storage: UnitOfWork, events: EventService, bare_profile_id: UUID
    ) -> None:
        await add_vector_neighbours(storage, bare_profile_id, "договор")
        expected = {
            await self.create(events, bare_profile_id, "Обсудить бюджет по договору"),
            await self.create(events, bare_profile_id, "Проверить договоры"),
            await self.create(events, bare_profile_id, "Подписать договор"),
        }
        await self.create(events, bare_profile_id, "Купить билеты")

        found = await events.search_events(EventFilter(bare_profile_id), "договор", limit=10)

        assert {card.id for card in found} == expected

    async def test_filters_limit_lemma_matches_too(
        self, storage: UnitOfWork, events: EventService, bare_profile_id: UUID
    ) -> None:
        await add_vector_neighbours(storage, bare_profile_id, "договор")
        meeting = await self.create(
            events,
            bare_profile_id,
            "Встреча по договору",
            type=EventType.MEETING,
            starts_at=HISTORY[0].starts_at,
        )
        await self.create(events, bare_profile_id, "Проверить договоры")

        found = await events.search_events(
            EventFilter(bare_profile_id, event_type=EventType.MEETING), "договор", limit=10
        )

        assert [card.id for card in found] == [meeting]

    async def test_other_profile_records_never_match(
        self, storage: UnitOfWork, events: EventService, bare_profile_id: UUID
    ) -> None:
        await self.create(events, bare_profile_id, "Проверить договоры")
        stranger = await storage.profiles.add(uuid4().hex, uuid4().hex)
        await storage.commit()

        found = await events.search_events(EventFilter(stranger.id), "договор", limit=10)

        assert found == []
