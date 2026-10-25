"""Записи через API: создание, изменение, удаление, фильтры и изоляция профилей."""

from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import EventType
from app.core.errors import ErrorCode
from app.core.events import EventDraft, EventService
from app.core.history_source import read_history_file
from app.core.queries import EventFilter
from app.core.schedule import MOSCOW
from app.core.search import SearchService
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer, SimilarityRanker
from app.storage.database import UnitOfWork
from app.storage.models import EventRecord
from tests.helpers import assert_error

pytestmark = pytest.mark.integration

HISTORY = read_history_file()
TOMORROW_15 = "2026-10-27T15:00:00+03:00"
TOMORROW_16 = "2026-10-27T16:00:00+03:00"
ALL = "200"


async def create(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    response = await client.post("/api/events", json=fields)
    assert response.status_code == 201, response.text
    event: dict[str, Any] = response.json()
    return event


async def list_events(client: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/api/events", params=params)
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["events"]
    return events


async def stored_index(db_engine: AsyncEngine, event_id: int) -> tuple[list[float], list[str]]:
    async with db_engine.connect() as connection:
        row = (
            await connection.execute(
                select(EventRecord.embedding, EventRecord.lemmas).where(EventRecord.id == event_id)
            )
        ).one()
    return row.embedding, row.lemmas


class TestCreate:
    async def test_task_without_due_date(self, client: httpx.AsyncClient) -> None:
        event = await create(client, type="task", title="  Купить билеты  ")

        assert event["title"] == "Купить билеты"
        assert event["starts_at"] is None
        assert event["has_time"] is False
        assert event["ends_at"] is None
        assert (event["status"], event["source"]) == ("open", "user")

    async def test_meeting_lasts_hour_by_default(self, client: httpx.AsyncClient) -> None:
        event = await create(
            client, type="meeting", title="Встреча с командой", starts_at=TOMORROW_15
        )

        assert event["starts_at"] == TOMORROW_15
        assert event["ends_at"] == TOMORROW_16

    async def test_time_is_returned_in_moscow(self, client: httpx.AsyncClient) -> None:
        event = await create(
            client, type="reminder", title="Позвонить Ивану", starts_at="2026-10-27T07:00:00Z"
        )

        assert event["starts_at"] == "2026-10-27T10:00:00+03:00"

    async def test_date_only_is_moscow_midnight(self, client: httpx.AsyncClient) -> None:
        event = await create(
            client,
            type="task",
            title="Отправить отчёт",
            starts_at="2026-10-30T18:45:00+03:00",
            has_time=False,
        )

        assert event["starts_at"] == "2026-10-30T00:00:00+03:00"
        assert event["has_time"] is False

    async def test_title_is_indexed_for_search(
        self, client: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        event = await create(client, type="task", title="Подготовить презентацию")

        embedding, lemmas = await stored_index(db_engine, event["id"])

        assert embedding == pytest.approx(
            await HashingEmbedder().embed_query("Подготовить презентацию"), abs=1e-6
        )
        assert lemmas == LowercaseLemmatizer().lemmas("Подготовить презентацию")

    @pytest.mark.parametrize(
        ("fields", "message_part"),
        [
            ({"type": "reminder", "title": "Позвонить"}, "дата и время"),
            ({"type": "meeting", "title": "Встреча", "starts_at": TOMORROW_15, "has_time": False},
             "дата и время"),
            ({"type": "task", "title": "Отчёт", "starts_at": TOMORROW_15, "ends_at": TOMORROW_16},
             "только у встречи"),
            ({"type": "meeting", "title": "Встреча", "starts_at": TOMORROW_16,
              "ends_at": TOMORROW_15}, "раньше"),
        ],
    )  # fmt: skip
    async def test_rules_violation_is_validation_error(
        self, client: httpx.AsyncClient, fields: dict[str, Any], message_part: str
    ) -> None:
        response = await client.post("/api/events", json=fields)

        assert_error(response, 422, ErrorCode.VALIDATION_ERROR)
        assert message_part in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "fields",
        [
            {"type": "task", "title": "   "},
            {"type": "task", "title": "Отчёт", "starts_at": "2026-10-27T15:00:00"},
            {"type": "task", "title": "Отчёт", "status": "done"},
        ],
    )
    async def test_malformed_body_is_validation_error(
        self, client: httpx.AsyncClient, fields: dict[str, Any]
    ) -> None:
        assert_error(await client.post("/api/events", json=fields), 422, ErrorCode.VALIDATION_ERROR)


class TestUpdate:
    async def test_mark_done(self, client: httpx.AsyncClient) -> None:
        event = await create(client, type="task", title="Купить билеты")

        response = await client.patch(f"/api/events/{event['id']}", json={"status": "done"})

        assert response.status_code == 200
        assert response.json()["status"] == "done"
        assert response.json()["title"] == "Купить билеты"

    async def test_new_title_recomputes_index(
        self, client: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        event = await create(client, type="task", title="Купить билеты")
        old_embedding, _ = await stored_index(db_engine, event["id"])

        response = await client.patch(
            f"/api/events/{event['id']}", json={"title": "Согласовать договор"}
        )

        embedding, lemmas = await stored_index(db_engine, event["id"])
        assert response.json()["title"] == "Согласовать договор"
        assert embedding != pytest.approx(old_embedding, abs=1e-6)
        assert embedding == pytest.approx(
            await HashingEmbedder().embed_query("Согласовать договор"), abs=1e-6
        )
        assert lemmas == ["согласовать", "договор"]

    async def test_moving_meeting_keeps_duration(self, client: httpx.AsyncClient) -> None:
        event = await create(
            client,
            type="meeting",
            title="Созвон",
            starts_at=TOMORROW_15,
            ends_at="2026-10-27T15:30:00+03:00",
        )

        response = await client.patch(
            f"/api/events/{event['id']}", json={"starts_at": "2026-10-28T11:00:00+03:00"}
        )

        assert response.json()["starts_at"] == "2026-10-28T11:00:00+03:00"
        assert response.json()["ends_at"] == "2026-10-28T11:30:00+03:00"

    async def test_null_due_date_clears_it_but_null_title_keeps_it(
        self, client: httpx.AsyncClient
    ) -> None:
        event = await create(client, type="task", title="Отчёт", starts_at=TOMORROW_15)

        response = await client.patch(
            f"/api/events/{event['id']}", json={"starts_at": None, "title": None}
        )

        assert response.json()["starts_at"] is None
        assert response.json()["has_time"] is False
        assert response.json()["title"] == "Отчёт"

    async def test_imported_history_can_be_reopened(self, client: httpx.AsyncClient) -> None:
        imported = (await list_events(client, limit="1"))[0]

        response = await client.patch(f"/api/events/{imported['id']}", json={"status": "open"})

        assert response.json()["status"] == "open"
        assert response.json()["source"] == "import"

    async def test_meeting_without_time_is_rejected(self, client: httpx.AsyncClient) -> None:
        event = await create(client, type="meeting", title="Демо", starts_at=TOMORROW_15)

        response = await client.patch(f"/api/events/{event['id']}", json={"has_time": False})

        assert_error(response, 422, ErrorCode.VALIDATION_ERROR)

    async def test_missing_event_is_not_found(self, client: httpx.AsyncClient) -> None:
        response = await client.patch("/api/events/999999999", json={"status": "done"})

        assert_error(response, 404, ErrorCode.NOT_FOUND)


class TestDelete:
    async def test_deleted_event_disappears(self, client: httpx.AsyncClient) -> None:
        event = await create(client, type="task", title="Купить билеты")

        response = await client.delete(f"/api/events/{event['id']}")

        assert response.status_code == 204
        assert response.content == b""
        assert_error(await client.delete(f"/api/events/{event['id']}"), 404, ErrorCode.NOT_FOUND)
        assert (await client.get("/api/me")).json()["events_count"] == len(HISTORY)


class TestFilters:
    async def test_period_matches_history(self, client: httpx.AsyncClient) -> None:
        start, end = "2024-03-01T00:00:00+03:00", "2024-04-01T00:00:00+03:00"
        expected = [
            (entry.title, entry.starts_at.isoformat())
            for entry in HISTORY
            if datetime.fromisoformat(start) <= entry.starts_at < datetime.fromisoformat(end)
        ]

        events = await list_events(client, **{"from": start, "to": end, "limit": ALL})

        assert expected
        assert [(event["title"], event["starts_at"]) for event in events] == expected

    async def test_period_is_half_open(self, client: httpx.AsyncClient) -> None:
        event = await create(client, type="meeting", title="Встреча", starts_at=TOMORROW_15)

        inside = await list_events(client, **{"from": TOMORROW_15, "to": TOMORROW_16})
        before = await list_events(
            client, **{"from": "2026-10-27T14:00:00+03:00", "to": TOMORROW_15}
        )

        assert [found["id"] for found in inside] == [event["id"]]
        assert before == []

    async def test_type_and_period_combine(self, client: httpx.AsyncClient) -> None:
        start, end = "2025-01-01T00:00:00+03:00", "2025-03-01T00:00:00+03:00"
        expected_count = sum(
            1
            for entry in HISTORY
            if entry.type is EventType.MEETING
            and datetime.fromisoformat(start) <= entry.starts_at < datetime.fromisoformat(end)
        )

        events = await list_events(
            client, **{"from": start, "to": end, "type": "meeting", "limit": ALL}
        )

        assert len(events) == expected_count > 0
        assert {event["type"] for event in events} == {"meeting"}

    async def test_status_filter(self, client: httpx.AsyncClient) -> None:
        task = await create(client, type="task", title="Купить билеты", starts_at=TOMORROW_15)

        open_events = await list_events(client, status="open", limit=ALL)
        done_events = await list_events(client, status="done", limit=ALL)

        assert {event["status"] for event in open_events} == {"open"}
        assert {event["status"] for event in done_events} == {"done"}
        assert task["id"] in {event["id"] for event in open_events}

    async def test_reversed_period_is_validation_error(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/events", params={"from": TOMORROW_16, "to": TOMORROW_15})

        assert_error(response, 422, ErrorCode.VALIDATION_ERROR)

    async def test_limit_is_applied(self, client: httpx.AsyncClient) -> None:
        assert len(await list_events(client, limit="3")) == 3
        assert len(await list_events(client)) == 50


class TestOrder:
    async def test_by_start_time_and_undated_last(
        self, storage: UnitOfWork, bare_profile_id: UUID
    ) -> None:
        search = SearchService(HashingEmbedder(), LowercaseLemmatizer(), SimilarityRanker())
        events = EventService(storage, search)
        tomorrow = datetime(2026, 10, 27, 15, 0, tzinfo=MOSCOW)
        undated = await events.create(bare_profile_id, EventDraft(EventType.TASK, "Когда-нибудь"))
        later = await events.create(
            bare_profile_id, EventDraft(EventType.TASK, "Потом", tomorrow.replace(hour=16))
        )
        sooner = await events.create(bare_profile_id, EventDraft(EventType.TASK, "Скоро", tomorrow))

        found = await events.list_events(EventFilter(bare_profile_id), limit=10)

        assert [card.id for card in found] == [sooner.id, later.id, undated.id]


class TestIsolation:
    async def test_other_profile_cannot_see_or_change_event(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        event = await create(
            client, type="task", title="Секретный отчёт Горького", starts_at=TOMORROW_15
        )
        path = f"/api/events/{event['id']}"

        assert_error(
            await other_device.patch(path, json={"status": "done"}), 404, ErrorCode.NOT_FOUND
        )
        assert_error(await other_device.delete(path), 404, ErrorCode.NOT_FOUND)
        same_day = {"from": TOMORROW_15, "to": TOMORROW_16}
        assert event["id"] not in {
            found["id"] for found in await list_events(other_device, **same_day)
        }
        found_by_other = await list_events(other_device, q="Секретный отчёт Горького")
        assert event["id"] not in {found["id"] for found in found_by_other}
        assert event["id"] in {found["id"] for found in await list_events(client, **same_day)}
