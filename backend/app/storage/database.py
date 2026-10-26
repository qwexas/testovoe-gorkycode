"""Подключение к PostgreSQL и единица работы (одна транзакция на запрос)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.storage.repositories import (
    ChatMessageRepository,
    DialogStateRepository,
    EventRepository,
    ProfileRepository,
    SeedEventRepository,
    UndoActionRepository,
)

PING_TIMEOUT_SECONDS = 3.0


class UnitOfWork:
    """Репозитории поверх одной сессии БД. Изменения фиксирует только `commit()`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.profiles = ProfileRepository(session)
        self.events = EventRepository(session)
        self.seed_events = SeedEventRepository(session)
        self.messages = ChatMessageRepository(session)
        self.dialog_states = DialogStateRepository(session)
        self.undo_actions = UndoActionRepository(session)

    async def flush(self) -> None:
        """Отправляет изменения в базу, не фиксируя транзакцию (серверные поля заполняются)."""
        await self._session.flush()

    async def commit(self) -> None:
        """Фиксирует транзакцию."""
        await self._session.commit()


class Database:
    """Пул соединений с PostgreSQL."""

    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[UnitOfWork]:
        """Открывает сессию; незафиксированные изменения откатываются при выходе."""
        async with self._sessions() as session:
            yield UnitOfWork(session)

    async def is_available(self) -> bool:
        """Отвечает ли база на `SELECT 1` за `PING_TIMEOUT_SECONDS`."""
        try:
            async with asyncio.timeout(PING_TIMEOUT_SECONDS), self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:  # проверка живости: любая ошибка соединения означает «недоступна»
            return False
        return True

    async def dispose(self) -> None:
        """Закрывает все соединения пула."""
        await self._engine.dispose()
