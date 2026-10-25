"""Общие фикстуры: настройки и приложение без базы данных."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import SearchBackend, Settings
from app.factory import create_app

TEST_APP_SECRET = "test-app-secret-for-pytest-only-0123456789"
TEST_PUBLIC_BASE_URL = "https://voice.example.test"
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://unit:unit@127.0.0.1:1/unit"
BASE_URL = "http://testserver"


def make_settings(database_url: str, **overrides: Any) -> Settings:
    """Настройки для тестов, независимые от `.env` разработчика; поиск — на заглушках."""
    values: dict[str, Any] = {
        "database_url": database_url,
        "app_secret": TEST_APP_SECRET,
        "cookie_secure": False,
        "public_base_url": TEST_PUBLIC_BASE_URL,
        "search_backend": SearchBackend.PLACEHOLDER,
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.fixture
def offline_app() -> FastAPI:
    """Приложение, у которого база недоступна: для проверок без Postgres."""
    return create_app(make_settings(UNREACHABLE_DATABASE_URL, load_history_on_startup=False))


@pytest.fixture
async def offline_client(offline_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент к приложению без базы."""
    async with (
        offline_app.router.lifespan_context(offline_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=offline_app), base_url=BASE_URL
        ) as client,
    ):
        yield client
