"""M1: реальная тестовая БД, явное создание и отсутствие побочных эффектов при отказах."""

from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.session_cookie import SESSION_COOKIE_NAME
from app.core.errors import ErrorCode
from app.core.history_source import read_history_file
from app.storage.models import EventRecord, ProfileRecord, ProfileSessionRecord
from tests.helpers import assert_error
from tests.integration.conftest import CREATE_HEADERS

pytestmark = pytest.mark.integration


async def counts(engine: AsyncEngine) -> tuple[int, ...]:
    async with engine.connect() as connection:
        return tuple(
            [
                int(await connection.scalar(select(func.count()).select_from(model)))
                for model in (ProfileRecord, ProfileSessionRecord, EventRecord)
            ]
        )


@pytest.mark.parametrize("session", ["missing", "unknown", "deleted", "revoked"])
async def test_refusals_have_no_database_or_model_side_effects(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    session: str,
) -> None:
    if session in {"deleted", "revoked"}:
        grant = await client.post("/api/profiles", headers=CREATE_HEADERS)
        assert grant.status_code == 201
        old = client.cookies.get(SESSION_COOKIE_NAME)
        if session == "deleted":
            await client.delete("/api/me")
        else:
            await client.post("/api/profiles", headers=CREATE_HEADERS)
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, old)
    elif session == "unknown":
        client.cookies.set(SESSION_COOKIE_NAME, "unknown-session")
    services = app.state.services
    admit = Mock(wraps=services.profile_onboarding.admit)
    seed = AsyncMock(wraps=services.profile_onboarding.seed)
    monkeypatch.setattr(services.profile_onboarding, "admit", admit)
    monkeypatch.setattr(services.profile_onboarding, "seed", seed)
    search = AsyncMock(wraps=services.search.search)
    monkeypatch.setattr(services.search, "search", search)
    llm, stt, tts = (
        Mock(parse=AsyncMock()),
        Mock(transcribe=AsyncMock()),
        Mock(synthesize=AsyncMock()),
    )
    app.state.services = replace(
        services, intent_parser=llm, speech_to_text=stt, text_to_speech=tts
    )
    before = await counts(db_engine)
    operations = [
        ("GET", "/api/me", {}),
        ("GET", "/api/events", {}),
        ("GET", "/api/events?q=отчёт", {}),
        ("GET", "/api/dialog", {}),
        ("GET", "/api/calendar.ics", {}),
        ("POST", "/api/chat", {"json": {"text": "Привет"}}),
        ("POST", "/api/voice", {"files": {"audio": ("voice", b"fake", "audio/ogg")}}),
        ("POST", "/api/tts", {"json": {"text": "Привет"}}),
        ("POST", "/api/events", {"json": {"type": "task", "title": "Тест"}}),
        ("PATCH", "/api/events/1", {"json": {"title": "Другое"}}),
        ("DELETE", "/api/events/1", {}),
        ("POST", "/api/actions/example/undo", {}),
    ]
    for method, path, options in operations:
        response = await client.request(method, path, **options)
        assert_error(response, 401, ErrorCode.SESSION_REQUIRED)
        assert "set-cookie" not in response.headers
        assert await counts(db_engine) == before
    admit.assert_not_called()
    seed.assert_not_called()
    llm.parse.assert_not_called()
    stt.transcribe.assert_not_called()
    tts.synthesize.assert_not_called()
    search.assert_not_called()


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "status"),
    [
        ("GET", "/api/me", {"Origin": "https://evil.test"}, None, 401),
        ("POST", "/api/profiles", {}, None, 403),
        ("POST", "/api/profiles", {"Origin": "http://testserver"}, None, 403),
        ("POST", "/api/profiles", {"Origin": "https://evil.test"}, {"create": "yes"}, 403),
        ("POST", "/api/profiles", {"X-Gorky-Client": "wrong"}, None, 403),
        ("POST", "/api/profiles", {"X-Gorky-Client": "web", "Origin": "null"}, None, 403),
        (
            "POST",
            "/api/profiles",
            {
                "X-Gorky-Client": "web",
                "Origin": "https://evil.test",
                "Host": "evil.test",
                "X-Forwarded-Host": "evil.test",
                "X-Forwarded-Proto": "https",
            },
            None,
            403,
        ),
        ("POST", "/api/profiles", {**CREATE_HEADERS, "Sec-Fetch-Site": "cross-site"}, None, 403),
        (
            "OPTIONS",
            "/api/profiles",
            {
                "Origin": "https://evil.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-gorky-client",
            },
            None,
            405,
        ),
    ],
)
async def test_browser_creation_triggers_are_rejected_without_writes(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, str] | None,
    status: int,
) -> None:
    before = await counts(db_engine)
    admit = Mock(wraps=app.state.services.profile_onboarding.admit)
    monkeypatch.setattr(app.state.services.profile_onboarding, "admit", admit)
    response = await client.request(method, path, headers=headers, data=body)
    assert response.status_code == status, response.text
    assert await counts(db_engine) == before
    assert "set-cookie" not in response.headers
    assert "access-control-allow-origin" not in response.headers
    admit.assert_not_called()


async def test_create_restore_delete_and_second_tab_polling(
    client: httpx.AsyncClient,
    other_device: httpx.AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    assert await counts(db_engine) == (0, 0, 0)
    grant = await client.post("/api/profiles", headers=CREATE_HEADERS)
    assert grant.status_code == 201
    profile = grant.json()
    assert profile["recovery_code"]
    size = len(read_history_file())
    assert await counts(db_engine) == (1, 1, size)
    assert (await client.get("/api/me")).json()["id"] == profile["id"]
    feed = profile["calendar_subscription_url"].split("/api/", 1)[1]
    assert (await other_device.get("/api/" + feed)).status_code == 200
    restored = await other_device.post(
        "/api/profiles/restore", json={"code": profile["recovery_code"]}
    )
    assert restored.status_code == 200 and restored.json()["id"] == profile["id"]
    assert await counts(db_engine) == (1, 2, size)
    await client.delete("/api/me")
    assert await counts(db_engine) == (0, 0, 0)
    for path in ("/api/me", "/api/events", "/api/dialog"):
        assert (await other_device.get(path)).status_code == 401
        assert await counts(db_engine) == (0, 0, 0)
