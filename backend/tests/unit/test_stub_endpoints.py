"""Эндпоинты, которые объявлены, но ещё не реализованы, отвечают 501.

Проверка валидации входа здесь же: она срабатывает до бизнес-логики и базы.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import get_current_profile
from app.core.errors import ErrorCode
from app.core.profiles import ProfileCard
from tests.helpers import assert_error

STUB_REQUESTS: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/voice", {"files": {"audio": ("voice.webm", b"\x1a\x45", "audio/webm")}}),
    ("POST", "/api/tts", {"json": {"text": "Привет", "voice": "baya"}}),
    ("GET", "/api/calendar.ics", {}),
    ("GET", "/api/calendar/secret-token.ics", {}),
]


@pytest.fixture
def stub_app(offline_app: FastAPI) -> FastAPI:
    profile = ProfileCard(
        id=uuid4(), created_at=datetime.now(UTC), events_count=0, calendar_token="token"
    )
    offline_app.dependency_overrides[get_current_profile] = lambda: profile
    return offline_app


@pytest.mark.parametrize(("method", "url", "options"), STUB_REQUESTS)
async def test_stub_answers_not_implemented(
    stub_app: FastAPI,
    offline_client: httpx.AsyncClient,
    method: str,
    url: str,
    options: dict[str, Any],
) -> None:
    response = await offline_client.request(method, url, **options)

    assert_error(response, 501, ErrorCode.NOT_IMPLEMENTED)


@pytest.mark.parametrize(
    ("method", "url", "options"),
    [
        ("POST", "/api/chat", {"json": {"text": "   "}}),
        ("POST", "/api/chat", {"json": {"text": "x" * 1001}}),
        ("POST", "/api/chat", {"json": {"text": "привет", "extra": 1}}),
        ("GET", "/api/dialog?limit=0", {}),
        ("POST", "/api/actions/" + "x" * 65 + "/undo", {}),
        ("GET", "/api/events?from=2026-10-26T00:00:00", {}),
        ("POST", "/api/events", {"json": {"type": "birthday", "title": "Праздник"}}),
        ("PATCH", "/api/events/abc", {"json": {}}),
    ],
)
async def test_invalid_input_is_validation_error(
    stub_app: FastAPI,
    offline_client: httpx.AsyncClient,
    method: str,
    url: str,
    options: dict[str, Any],
) -> None:
    response = await offline_client.request(method, url, **options)

    assert_error(response, 422, ErrorCode.VALIDATION_ERROR)
