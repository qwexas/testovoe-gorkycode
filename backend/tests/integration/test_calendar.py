"""Календарь `.ics` через API на настоящем Postgres: состав, предупреждения, подписка, изоляция."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from icalendar import Calendar, Event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.calendar import SubscriptionThrottle
from app.core.errors import ErrorCode
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.schedule import MOSCOW
from app.storage.models import ProfileRecord
from tests.helpers import assert_error

pytestmark = pytest.mark.integration


def today() -> date:
    return datetime.now(MOSCOW).date()


def moment(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=MOSCOW)


async def create(client: httpx.AsyncClient, **fields: Any) -> int:
    response = await client.post("/api/events", json=fields)
    assert response.status_code == 201, response.text
    event_id: int = response.json()["id"]
    return event_id


def uid(event_id: int) -> str:
    return f"event-{event_id}@voice.wexasas.online"


def events_by_uid(content: bytes) -> dict[str, Event]:
    calendar = Calendar.from_ical(content)
    return {str(event["UID"]): event for event in calendar.walk("VEVENT")}


async def download(client: httpx.AsyncClient) -> dict[str, Event]:
    response = await client.get("/api/calendar.ics")
    assert response.status_code == 200, response.text
    return events_by_uid(response.content)


async def subscription_path(client: httpx.AsyncClient) -> str:
    url = (await client.get("/api/me")).json()["calendar_subscription_url"]
    assert url.startswith("webcal://")
    return urlsplit(url).path


async def profiles_count(db_engine: AsyncEngine) -> int:
    async with db_engine.connect() as connection:
        count: int = await connection.scalar(select(func.count()).select_from(ProfileRecord))
    return count


class TestDownload:
    async def test_open_dated_records_from_today_with_alerts(
        self, client: httpx.AsyncClient
    ) -> None:
        tomorrow = today() + timedelta(days=1)
        meeting = await create(
            client,
            type="meeting",
            title="Встреча с командой",
            starts_at=moment(tomorrow, 15).isoformat(),
        )
        reminder = await create(
            client,
            type="reminder",
            title="Позвонить Ивану",
            starts_at=moment(tomorrow, 10).isoformat(),
        )
        dated_task = await create(
            client,
            type="task",
            title="Отправить отчёт",
            starts_at=moment(tomorrow, 0).isoformat(),
            has_time=False,
        )
        undated = await create(client, type="task", title="Купить билеты")
        past = await create(
            client,
            type="meeting",
            title="Вчерашняя встреча",
            starts_at=moment(today() - timedelta(days=1), 15).isoformat(),
        )
        done = await create(
            client, type="task", title="Сделано", starts_at=moment(tomorrow, 12).isoformat()
        )
        await client.patch(f"/api/events/{done}", json={"status": "done"})

        response = await client.get("/api/calendar.ics")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/calendar; charset=utf-8"
        assert response.headers["content-disposition"] == 'attachment; filename="gorky.ics"'
        events = events_by_uid(response.content)
        assert {uid(meeting), uid(reminder), uid(dated_task)} <= set(events)
        assert {uid(undated), uid(past), uid(done)}.isdisjoint(events)

        meeting_event = events[uid(meeting)]
        assert meeting_event.decoded("DTSTART") == moment(tomorrow, 15)
        assert meeting_event.decoded("DTEND") == moment(tomorrow, 16)
        assert meeting_event["DTSTART"].params["TZID"] == "Europe/Moscow"
        [meeting_alarm] = meeting_event.walk("VALARM")
        assert meeting_alarm.decoded("TRIGGER") == timedelta(minutes=-15)

        [reminder_alarm] = events[uid(reminder)].walk("VALARM")
        assert reminder_alarm.decoded("TRIGGER") == timedelta(0)
        assert events[uid(dated_task)].decoded("DTSTART") == tomorrow

    async def test_history_is_included_only_from_today_and_open(
        self, client: httpx.AsyncClient
    ) -> None:
        events = await download(client)
        done = (await client.get("/api/events", params={"status": "done", "limit": 200})).json()

        assert events, "в истории из CSV есть будущие записи"
        for event in events.values():
            start = event.decoded("DTSTART")
            start_day = (
                start if not isinstance(start, datetime) else start.astimezone(MOSCOW).date()
            )
            assert start_day >= today()
            assert event.walk("VALARM")
        assert {uid(event["id"]) for event in done["events"]}.isdisjoint(events)


class TestSubscription:
    async def test_same_calendar_without_cookie_and_without_new_profile(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        await create(
            client,
            type="meeting",
            title="Планёрка",
            starts_at=moment(today() + timedelta(days=2), 11).isoformat(),
        )
        path = await subscription_path(client)
        profiles_before = await profiles_count(db_engine)

        response = await other_device.get(path)

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "text/calendar; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache"
        assert "set-cookie" not in response.headers
        assert set(events_by_uid(response.content)) == set(await download(client))
        assert await profiles_count(db_engine) == profiles_before

    async def test_invalid_cookie_does_not_create_profile(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        path = await subscription_path(client)
        profiles_before = await profiles_count(db_engine)

        response = await other_device.get(path, headers={"Cookie": "gorky_session=garbage"})

        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert await profiles_count(db_engine) == profiles_before

    async def test_profiles_are_isolated(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        starts_at = moment(today() + timedelta(days=1), 18).isoformat()
        mine = await create(client, type="meeting", title="Секрет первого", starts_at=starts_at)
        theirs = await create(
            other_device, type="meeting", title="Секрет второго", starts_at=starts_at
        )

        my_calendar = events_by_uid((await client.get(await subscription_path(client))).content)
        their_calendar = events_by_uid(
            (await client.get(await subscription_path(other_device))).content
        )

        assert uid(mine) in my_calendar and uid(theirs) not in my_calendar
        assert uid(theirs) in their_calendar and uid(mine) not in their_calendar

    @pytest.mark.parametrize("token", ["unknown-token", "x" * 64])
    async def test_unknown_token_is_404(self, client: httpx.AsyncClient, token: str) -> None:
        response = await client.get(f"/api/calendar/{token}.ics")

        assert_error(response, 404, ErrorCode.NOT_FOUND)

    async def test_token_of_deleted_profile_is_404(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        path = await subscription_path(client)
        assert (await client.delete("/api/me")).status_code == 204

        response = await other_device.get(path)

        assert_error(response, 404, ErrorCode.NOT_FOUND)

    async def test_requests_are_limited_per_ip(
        self, app: FastAPI, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        limiter = SlidingWindowRateLimiter(max_hits=1, window_seconds=60)
        app.state.services = replace(
            app.state.services, subscription_throttle=SubscriptionThrottle(limiter)
        )
        path = await subscription_path(client)
        first_ip = {"CF-Connecting-IP": "203.0.113.5"}
        assert (await other_device.get(path, headers=first_ip)).status_code == 200

        limited = await other_device.get(path, headers=first_ip)
        other_ip = await other_device.get(path, headers={"CF-Connecting-IP": "203.0.113.6"})

        assert_error(limited, 429, ErrorCode.RATE_LIMITED)
        assert limited.headers["retry-after"] == "60"
        assert other_ip.status_code == 200


@pytest.fixture(name="client")
def authenticated_client(profile_client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Операции профиля проверяются после явного создания, без скрытого onboarding."""
    return profile_client


@pytest.fixture(name="other_device")
def authenticated_other_device(other_profile_client: httpx.AsyncClient) -> httpx.AsyncClient:
    return other_profile_client
