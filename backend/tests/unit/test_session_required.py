"""Отказ до создания данных и вызова моделей, в том числе без доступной БД."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import get_profile_service
from app.api.session_cookie import SESSION_COOKIE_NAME
from app.core.errors import ErrorCode
from tests.helpers import assert_error


@pytest.mark.parametrize("path", ["/api/me", "/api/events", "/api/dialog", "/api/calendar.ics"])
async def test_missing_session_is_read_only_without_database(
    offline_client: httpx.AsyncClient,
    path: str,
) -> None:
    response = await offline_client.get(path)
    assert_error(response, 401, ErrorCode.SESSION_REQUIRED)
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("cookie", ["", "unknown", "revoked"])
async def test_invalid_sessions_never_call_onboarding(
    offline_app: FastAPI,
    offline_client: httpx.AsyncClient,
    cookie: str,
) -> None:
    service = Mock(find_by_session=AsyncMock(return_value=None), create_profile=AsyncMock())
    offline_app.dependency_overrides[get_profile_service] = lambda: service
    if cookie:
        offline_client.cookies.set(SESSION_COOKIE_NAME, cookie)
    response = await offline_client.get("/api/me")
    assert_error(response, 401, ErrorCode.SESSION_REQUIRED)
    service.create_profile.assert_not_called()
    service.find_by_session.assert_awaited_once_with(cookie or None)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://testserver"},
        {"X-Gorky-Client": "web", "Origin": "https://evil.test"},
        {"X-Gorky-Client": "web", "Origin": "null"},
        {"X-Gorky-Client": "web", "Sec-Fetch-Site": "cross-site"},
    ],
)
async def test_creation_guard_runs_before_storage(
    offline_client: httpx.AsyncClient,
    headers: dict[str, str],
) -> None:
    response = await offline_client.post("/api/profiles", headers=headers)
    assert_error(response, 403, ErrorCode.FORBIDDEN)
    assert "set-cookie" not in response.headers
