"""Окружение Alembic: асинхронное подключение через asyncpg.

Адрес базы: `config.attributes["database_url"]` (так его передают тесты),
иначе `DATABASE_URL` из настроек приложения. Тесты отключают настройку логов
через `config.attributes["configure_logger"] = False`.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.storage.models import Base

config = context.config
target_metadata = Base.metadata

if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    url = config.attributes.get("database_url")
    return url if isinstance(url, str) else get_settings().database_url


def _configure_and_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_configure_and_run)
    await engine.dispose()


def _run_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    _run_offline()
else:
    asyncio.run(_run_online())
