"""Диалог через API на настоящем Postgres: чат → история → отмена, изоляция, лимит, сбой LLM.

Разбор реплик подменён `FakeIntentParser`: проверяется бизнес-логика, хранение и HTTP,
а не языковая модель. Даты — относительно настоящего «сейчас» по Москве.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import EventType
from app.core.errors import ErrorCode
from app.core.schedule import MOSCOW
from app.llm.errors import LLMUnavailableError
from app.nlu.interfaces import Action, Intent, TimeScope, When
from app.storage.models import DialogStateRecord
from tests.helpers import assert_error
from tests.unit.dialog.support import FakeIntentParser, about, answer, create, simple

pytestmark = pytest.mark.integration


def tomorrow() -> date:
    return datetime.now(MOSCOW).date() + timedelta(days=1)


def moment(day: date, hour: int, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute), tzinfo=MOSCOW).isoformat()


@pytest.fixture
def parser(app: FastAPI) -> FakeIntentParser:
    """Разбор по сценарию теста вместо GigaChat."""
    fake = FakeIntentParser()
    app.state.services = replace(app.state.services, intent_parser=fake)
    return fake


async def chat(
    client: httpx.AsyncClient, parser: FakeIntentParser, intent: Intent
) -> dict[str, Any]:
    parser.script[intent.text] = intent
    response = await client.post("/api/chat", json={"text": intent.text})
    assert response.status_code == 200, response.text
    reply: dict[str, Any] = response.json()
    return reply


async def history(client: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/api/dialog", params=params)
    assert response.status_code == 200, response.text
    messages: list[dict[str, Any]] = response.json()["messages"]
    return messages


def team_meeting() -> Intent:
    return create(
        "Добавь встречу с командой завтра в 15:00",
        EventType.MEETING,
        "Встреча с командой",
        date=tomorrow(),
        time=time(15),
    )


class TestFullCycle:
    async def test_chat_history_undo(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        reply = await chat(client, parser, team_meeting())

        assert reply["kind"] == "confirmation"
        assert reply["text"].startswith("Встреча «Встреча с командой» — завтра, ")
        [event] = reply["events"]
        assert event["starts_at"] == moment(tomorrow(), 15)
        assert event["ends_at"] == moment(tomorrow(), 16)
        assert reply["undo"]["action_id"]

        messages = await history(client)
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["text"] == "Добавь встречу с командой завтра в 15:00"
        assert messages[0]["reply"] is None
        assert messages[1]["reply"] == reply
        assert reply["message_id"] == messages[1]["id"]

        undone = await client.post(f"/api/actions/{reply['undo']['action_id']}/undo")
        assert undone.status_code == 200, undone.text
        assert undone.json()["kind"] == "confirmation"
        assert undone.json()["text"] == "Отменил: «Встреча с командой» больше нет в плане."
        events = await client.get("/api/events", params={"q": "Встреча с командой"})
        assert all(e["id"] != event["id"] for e in events.json()["events"])

        again = await client.post(f"/api/actions/{reply['undo']['action_id']}/undo")
        assert_error(again, 404, ErrorCode.NOT_FOUND)
        assert again.json()["error"]["message"] == "Отменить уже нельзя."
        assert [m["role"] for m in await history(client)] == ["user", "assistant", "assistant"]

    async def test_clarification_survives_between_requests(
        self, client: httpx.AsyncClient, parser: FakeIntentParser, db_engine: AsyncEngine
    ) -> None:
        question = await chat(
            client,
            parser,
            create(
                "Поставь встречу с Иваном завтра",
                EventType.MEETING,
                "Встреча с Иваном",
                date=tomorrow(),
            ),
        )
        assert question["kind"] == "clarification"
        assert question["pending"] == {
            "expects": "time",
            "question": "На какое время поставить встречу?",
        }
        async with db_engine.connect() as connection:
            stored = (await connection.execute(select(DialogStateRecord.pending))).scalar_one()
        assert stored["intent"]["title"] == "Встреча с Иваном"

        created = await chat(client, parser, answer("в 15", time=time(15)))

        assert created["kind"] == "confirmation"
        assert created["events"][0]["starts_at"] == moment(tomorrow(), 15)
        context = parser.contexts[-1]
        assert context.pending_question == "На какое время поставить встречу?"
        assert [turn.role for turn in context.recent] == ["user", "assistant"]

    async def test_delete_confirm_and_undo_restores_same_id(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        created = await client.post(
            "/api/events", json={"type": "task", "title": "Купить билеты в театр"}
        )
        event_id = created.json()["id"]

        asked = await chat(
            client,
            parser,
            Intent(Action.DELETE, "Удали билеты в театр", target=about("билеты в театр")),
        )
        deleted = await chat(client, parser, simple(Action.CONFIRM, "да"))
        restored = await client.post(f"/api/actions/{deleted['undo']['action_id']}/undo")

        assert asked["kind"] == "confirm_request"
        assert asked["events"][0]["id"] == event_id
        assert deleted["text"] == "Удалил задачу «Купить билеты в театр»."
        assert restored.json()["events"][0]["id"] == event_id
        found = await client.get("/api/events", params={"q": "билеты в театр"})
        assert event_id in [e["id"] for e in found.json()["events"]]

    async def test_reschedule_and_undo(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        await chat(client, parser, team_meeting())

        moved = await chat(
            client,
            parser,
            Intent(Action.RESCHEDULE, "Перенеси её на 17", target=None, when=When(time=time(17))),
        )
        await client.post(f"/api/actions/{moved['undo']['action_id']}/undo")

        assert moved["events"][0]["starts_at"] == moment(tomorrow(), 17)
        assert moved["events"][0]["ends_at"] == moment(tomorrow(), 18)
        events = await client.get(
            "/api/events",
            params={
                "from": moment(tomorrow(), 0),
                "to": moment(tomorrow() + timedelta(days=1), 0),
                "type": "meeting",
            },
        )
        mine = [e for e in events.json()["events"] if e["title"] == "Встреча с командой"]
        assert [e["starts_at"] for e in mine] == [moment(tomorrow(), 15)]

    async def test_conflict_found_in_database(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        await client.post(
            "/api/events",
            json={
                "type": "meeting",
                "title": "Планёрка отдела",
                "starts_at": moment(tomorrow(), 15),
            },
        )

        reply = await chat(
            client,
            parser,
            create(
                "Встреча завтра в 15:30",
                EventType.MEETING,
                "Разбор",
                date=tomorrow(),
                time=time(15, 30),
            ),
        )

        assert reply["kind"] == "confirm_request"
        assert "Планёрка отдела" in [c["title"] for c in reply["conflicts"]]
        assert reply["pending"]["expects"] == "confirm"

    async def test_search_in_csv_history(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        reply = await chat(
            client,
            parser,
            Intent(
                Action.SEARCH,
                "Когда у меня была встреча с Иваном?",
                query="встреча с Иваном",
                event_type=EventType.MEETING,
                time_scope=TimeScope.PAST,
            ),
        )

        assert reply["kind"] == "search_results"
        assert reply["text"].startswith("Последняя встреча «Встреча с Иваном")
        assert reply["events"][0]["starts_at"] < datetime.now(MOSCOW).isoformat()

    async def test_history_pagination(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        for number in range(3):
            await chat(client, parser, simple(Action.SMALLTALK, f"привет {number}"))

        newest = await history(client, limit="2")
        older = await history(client, limit="10", before_id=str(newest[0]["id"]))

        assert [m["role"] for m in newest] == ["user", "assistant"]
        assert newest[0]["text"] == "привет 2"
        assert len(older) == 4
        assert older[-1]["id"] < newest[0]["id"]


class TestContextBetweenRequests:
    async def test_it_after_list_of_two_asks_which(
        self, client: httpx.AsyncClient, parser: FakeIntentParser, db_engine: AsyncEngine
    ) -> None:
        today = datetime.now(MOSCOW).date()
        for title, hour in (("Позвонить маме", 10), ("Полить цветы", 11)):
            created = await client.post(
                "/api/events",
                json={"type": "reminder", "title": title, "starts_at": moment(today, hour)},
            )
            assert created.status_code == 201, created.text

        listed = await chat(
            client,
            parser,
            Intent(Action.LIST, "Какие напоминания сегодня?", event_type=EventType.REMINDER),
        )
        async with db_engine.connect() as connection:
            peers = (await connection.execute(select(DialogStateRecord.focus_peers))).scalar_one()
        asked = await chat(client, parser, Intent(Action.COMPLETE, "Отметь её выполненной"))

        assert len(listed["events"]) == 2
        assert peers == 2
        assert asked["kind"] == "choice"
        assert asked["text"] == "Какое напоминание отметить сделанным?"
        assert [c["event"]["title"] for c in asked["choices"]] == ["Позвонить маме", "Полить цветы"]

    async def test_repeated_reminder_asks_before_adding(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        reminder = create(
            "Напомни завтра в 10 позвонить Ивану",
            EventType.REMINDER,
            "Позвонить Ивану",
            date=tomorrow(),
            time=time(10),
        )
        await chat(client, parser, reminder)

        again = await chat(client, parser, reminder)

        assert again["kind"] == "confirm_request"
        assert again["text"] == (
            "Такое напоминание уже есть: «Позвонить Ивану» — завтра в 10:00. Добавить ещё одно?"
        )


class TestIsolation:
    async def test_profiles_do_not_see_each_other(
        self,
        client: httpx.AsyncClient,
        other_device: httpx.AsyncClient,
        parser: FakeIntentParser,
    ) -> None:
        reply = await chat(client, parser, team_meeting())

        foreign_undo = await other_device.post(f"/api/actions/{reply['undo']['action_id']}/undo")
        foreign_delete = await chat(other_device, parser, Intent(Action.DELETE, "Удали её"))

        assert_error(foreign_undo, 404, ErrorCode.NOT_FOUND)
        assert foreign_delete["text"].startswith("Не понял, о какой записи речь.")
        assert [m["text"] for m in await history(other_device)] == [
            "Удали её",
            foreign_delete["text"],
        ]
        assert len(await history(client)) == 2


class TestLimitsAndFailures:
    async def test_twenty_messages_per_minute(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        for number in range(20):
            await chat(client, parser, simple(Action.SMALLTALK, f"привет {number}"))
        parser.script["ещё"] = simple(Action.SMALLTALK, "ещё")

        response = await client.post("/api/chat", json={"text": "ещё"})

        assert_error(response, 429, ErrorCode.RATE_LIMITED)
        assert 1 <= int(response.headers["Retry-After"]) <= 60
        assert len(await history(client, limit="200")) == 40

    async def test_llm_failure_keeps_user_message(
        self, client: httpx.AsyncClient, parser: FakeIntentParser
    ) -> None:
        parser.script["Что у меня сегодня?"] = LLMUnavailableError()

        response = await client.post("/api/chat", json={"text": "Что у меня сегодня?"})

        assert_error(response, 503, ErrorCode.LLM_UNAVAILABLE)
        messages = await history(client)
        assert [(m["role"], m["text"], m["reply"]) for m in messages] == [
            ("user", "Что у меня сегодня?", None)
        ]

    async def test_without_llm_chat_is_unavailable(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/api/chat", json={"text": "Привет"})

        assert_error(response, 503, ErrorCode.LLM_UNAVAILABLE)
