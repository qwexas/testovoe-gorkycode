"""Неверный ввод отклоняется в едином формате ошибок до бизнес-логики и базы."""

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


@pytest.fixture
def known_profile_app(offline_app: FastAPI) -> FastAPI:
    """Приложение без базы, где текущий профиль уже известен."""
    profile = ProfileCard(
        id=uuid4(), created_at=datetime.now(UTC), events_count=0, calendar_token="token"
    )
    offline_app.dependency_overrides[get_current_profile] = lambda: profile
    return offline_app


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
        ("POST", "/api/tts", {"json": {"text": "  "}}),
        ("POST", "/api/tts", {"json": {"text": "Привет", "voice": "x" * 33}}),
        ("POST", "/api/voice", {"json": {"audio": "не файл"}}),
        ("POST", "/api/voice", {"data": {"text": "без записи"}}),
        ("GET", "/api/calendar/" + "x" * 65 + ".ics", {}),
    ],
)
async def test_invalid_input_is_validation_error(
    known_profile_app: FastAPI,
    offline_client: httpx.AsyncClient,
    method: str,
    url: str,
    options: dict[str, Any],
) -> None:
    response = await offline_client.request(method, url, **options)

    assert_error(response, 422, ErrorCode.VALIDATION_ERROR)
