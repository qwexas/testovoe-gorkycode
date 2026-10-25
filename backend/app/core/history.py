"""Точка расширения: история записей, которую получает каждый новый профиль.

По решению Q22 новый профиль получает 1000 записей из CSV как историю. Загрузка
CSV появится на контрольной точке 2 — отдельной реализацией `ProfileHistorySeeder`,
которая подключается в `app.factory.create_app`.
"""

from typing import Protocol
from uuid import UUID

from app.storage.database import UnitOfWork


class ProfileHistorySeeder(Protocol):
    """Заполняет только что созданный профиль историей в той же транзакции."""

    async def seed(self, storage: UnitOfWork, profile_id: UUID) -> None:
        """Добавляет записи истории профилю `profile_id`, не фиксируя транзакцию."""
        ...


class EmptyProfileHistory:
    """Профиль без истории — пока импорт CSV не подключён."""

    async def seed(self, storage: UnitOfWork, profile_id: UUID) -> None:
        """Ничего не добавляет."""
