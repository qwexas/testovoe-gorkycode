"""Фикстуры с настоящим PostgreSQL из `DATABASE_URL_TEST`.

Если переменная не задана или сервер недоступен, интеграционные тесты пропускаются
с объяснением. Тестовая база создаётся при необходимости, к ней применяются миграции,
перед каждым тестом таблицы очищаются.
"""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import ENV_FILE, REPOSITORY_ROOT
from app.factory import create_app
from app.storage.models import Base
from tests.conftest import BASE_URL, make_settings

BACKEND_DIR = REPOSITORY_ROOT / "backend"
CONNECT_TIMEOUT_SECONDS = 3


class _TestEnvironment(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url_test: str | None = None


def _asyncpg_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _ensure_database_exists(url: URL) -> None:
    try:
        connection = await asyncpg.connect(_asyncpg_dsn(url), timeout=CONNECT_TIMEOUT_SECONDS)
    except asyncpg.InvalidCatalogNameError:
        admin = await asyncpg.connect(
            _asyncpg_dsn(url.set(database="postgres")), timeout=CONNECT_TIMEOUT_SECONDS
        )
        try:
            await admin.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await admin.close()
    else:
        await connection.close()


def _apply_migrations(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def database_url() -> str:
    """Адрес подготовленной тестовой базы или skip с причиной."""
    raw_url = _TestEnvironment().database_url_test
    if not raw_url:
        pytest.skip("DATABASE_URL_TEST не задан — интеграционные тесты пропущены")
    url = make_url(raw_url)
    if "test" not in (url.database or ""):
        pytest.fail(
            f"DATABASE_URL_TEST должен указывать на отдельную тестовую базу, а не {url.database!r}"
        )
    try:
        asyncio.run(_ensure_database_exists(url))
    except (OSError, TimeoutError, asyncpg.PostgresError) as error:
        pytest.skip(
            f"Postgres по DATABASE_URL_TEST недоступен ({type(error).__name__}: {error}). "
            "Запустите `make db`."
        )
    _apply_migrations(raw_url)
    return raw_url


async def _truncate_all_tables(database_url: str) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
async def app(database_url: str) -> FastAPI:
    """Приложение на чистой тестовой базе."""
    await _truncate_all_tables(database_url)
    return create_app(make_settings(database_url))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент со своим хранилищем cookie — как отдельное устройство."""
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client,
    ):
        yield client


@pytest.fixture
async def other_device(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Второе устройство того же пользователя: отдельные cookie."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as client:
        yield client
