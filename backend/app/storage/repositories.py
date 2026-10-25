"""Репозитории: запросы к таблицам. Транзакцией управляет `UnitOfWork`."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import EventRecord, ProfileRecord, ProfileSessionRecord


class ProfileRepository:
    """Профили и их сессии."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, recovery_code_digest: str, calendar_token: str) -> ProfileRecord:
        """Создаёт профиль и возвращает его с заполненными `id` и `created_at`."""
        profile = ProfileRecord(
            recovery_code_digest=recovery_code_digest,
            calendar_token=calendar_token,
        )
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    async def get_by_session(self, token_digest: str) -> ProfileRecord | None:
        """Профиль, которому принадлежит сессия с данным отпечатком токена."""
        statement = (
            select(ProfileRecord)
            .join(ProfileSessionRecord, ProfileSessionRecord.profile_id == ProfileRecord.id)
            .where(ProfileSessionRecord.token_digest == token_digest)
        )
        return await self._session.scalar(statement)

    async def get_by_recovery_code(self, recovery_code_digest: str) -> ProfileRecord | None:
        """Профиль по отпечатку кода восстановления."""
        statement = select(ProfileRecord).where(
            ProfileRecord.recovery_code_digest == recovery_code_digest
        )
        return await self._session.scalar(statement)

    async def add_session(self, profile_id: UUID, token_digest: str) -> None:
        """Привязывает новую сессию устройства к профилю."""
        self._session.add(ProfileSessionRecord(token_digest=token_digest, profile_id=profile_id))
        await self._session.flush()

    async def delete_session(self, token_digest: str) -> None:
        """Удаляет сессию устройства, если она есть."""
        await self._session.execute(
            delete(ProfileSessionRecord).where(ProfileSessionRecord.token_digest == token_digest)
        )

    async def delete(self, profile_id: UUID) -> None:
        """Удаляет профиль; записи, диалог и сессии удаляются каскадом в базе."""
        await self._session.execute(delete(ProfileRecord).where(ProfileRecord.id == profile_id))


class EventRepository:
    """Задачи, напоминания и встречи профиля."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_for_profile(self, profile_id: UUID) -> int:
        """Количество записей профиля."""
        statement = (
            select(func.count())
            .select_from(EventRecord)
            .where(EventRecord.profile_id == profile_id)
        )
        return await self._session.scalar(statement) or 0
