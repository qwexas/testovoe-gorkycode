"""Анонимные профили (решение Q11): создание, вход по коду восстановления, удаление.

Профиль узнаётся по токену сессии из cookie. В базе хранятся только SHA-256
токена и HMAC кода восстановления, поэтому утечка базы не даёт войти в профиль.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.errors import InvalidRecoveryCodeError, TooManyProfilesError
from app.core.history import ProfileHistorySeeder
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.recovery import RecoveryCodes
from app.core.tokens import hash_session_token, new_calendar_token, new_session_token
from app.storage.database import UnitOfWork
from app.storage.models import ProfileRecord

PROFILE_CREATIONS_PER_ADDRESS = 20
PROFILE_CREATION_WINDOW_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class ProfileCard:
    """Сведения о профиле для показа пользователю.

    `recovery_code` заполнен только сразу после создания профиля — потом код
    восстановить нельзя, в базе лежит лишь его отпечаток.
    """

    id: UUID
    created_at: datetime
    events_count: int
    calendar_token: str
    recovery_code: str | None = None


@dataclass(frozen=True, slots=True)
class SessionGrant:
    """Профиль и новый токен сессии, который нужно отдать устройству."""

    profile: ProfileCard
    session_token: str


class ProfileOnboarding:
    """Появление нового профиля: не чаще лимита с одного адреса и сразу с историей (Q22).

    Лимит — `PROFILE_CREATIONS_PER_ADDRESS` профилей за `PROFILE_CREATION_WINDOW_SECONDS`
    с одного IP; лимит действует при явном создании через POST /api/profiles.
    """

    def __init__(
        self, history: ProfileHistorySeeder, creations: SlidingWindowRateLimiter | None = None
    ) -> None:
        self._history = history
        self._creations = creations or SlidingWindowRateLimiter(
            max_hits=PROFILE_CREATIONS_PER_ADDRESS,
            window_seconds=PROFILE_CREATION_WINDOW_SECONDS,
        )

    def admit(self, requester: str) -> None:
        """Учитывает создание профиля с адреса `requester`.

        Raises:
            TooManyProfilesError: С этого адреса лимит профилей исчерпан.
        """
        decision = self._creations.hit(requester)
        if not decision.allowed:
            raise TooManyProfilesError(decision.retry_after_seconds)

    async def seed(self, storage: UnitOfWork, profile_id: UUID) -> None:
        """Добавляет только что созданному профилю историю, не фиксируя транзакцию."""
        await self._history.seed(storage, profile_id)


class ProfileService:
    """Сценарии работы с профилем. Каждый изменяющий сценарий — одна транзакция."""

    def __init__(
        self,
        storage: UnitOfWork,
        recovery_codes: RecoveryCodes,
        onboarding: ProfileOnboarding,
    ) -> None:
        self._storage = storage
        self._recovery_codes = recovery_codes
        self._onboarding = onboarding

    async def find_by_session(self, session_token: str | None) -> ProfileCard | None:
        """Профиль по токену из cookie или `None`, если токена нет или он чужой."""
        profile = await self._profile_of_session(session_token)
        return None if profile is None else await self._card(profile)

    async def create_profile(self, replaced_session: str | None, requester: str) -> SessionGrant:
        """Создаёт профиль с историей и открывает на этом устройстве новую сессию.

        Args:
            replaced_session: Прежний токен устройства; его сессия закрывается.
            requester: Кто создаёт профиль (IP) — для лимита созданий.

        Raises:
            TooManyProfilesError: С этого адреса создано слишком много профилей.
        """
        self._onboarding.admit(requester)
        issued_code = self._recovery_codes.issue()
        profile = await self._storage.profiles.add(
            recovery_code_digest=issued_code.digest,
            calendar_token=new_calendar_token(),
        )
        await self._onboarding.seed(self._storage, profile.id)
        session_token = await self._switch_session(profile.id, replaced_session)
        card = await self._card(profile, recovery_code=issued_code.code)
        await self._storage.commit()
        return SessionGrant(profile=card, session_token=session_token)

    async def restore(
        self, recovery_code: str, requester: str, replaced_session: str | None
    ) -> SessionGrant:
        """Входит в профиль по коду восстановления.

        Args:
            recovery_code: Код в том виде, как его ввёл пользователь.
            requester: Кто пытается войти (IP) — для лимита попыток.
            replaced_session: Прежний токен устройства; его сессия закрывается.

        Raises:
            TooManyAttemptsError: Исчерпан лимит попыток.
            InvalidRecoveryCodeError: Код не подходит ни к одному профилю.
        """
        digest = self._recovery_codes.digest_attempt(recovery_code, requester)
        profile = await self._storage.profiles.get_by_recovery_code(digest)
        if profile is None:
            raise InvalidRecoveryCodeError()
        session_token = await self._switch_session(profile.id, replaced_session)
        card = await self._card(profile)
        await self._storage.commit()
        return SessionGrant(profile=card, session_token=session_token)

    async def delete_profile(self, session_token: str | None) -> None:
        """Удаляет профиль сессии со всеми данными; без профиля ничего не делает."""
        profile = await self._profile_of_session(session_token)
        if profile is None:
            return
        await self._storage.profiles.delete(profile.id)
        await self._storage.commit()

    async def _profile_of_session(self, session_token: str | None) -> ProfileRecord | None:
        if not session_token:
            return None
        return await self._storage.profiles.get_by_session(hash_session_token(session_token))

    async def _switch_session(self, profile_id: UUID, replaced_session: str | None) -> str:
        if replaced_session:
            await self._storage.profiles.delete_session(hash_session_token(replaced_session))
        session_token = new_session_token()
        await self._storage.profiles.add_session(profile_id, hash_session_token(session_token))
        return session_token

    async def _card(self, profile: ProfileRecord, recovery_code: str | None = None) -> ProfileCard:
        return ProfileCard(
            id=profile.id,
            created_at=profile.created_at,
            events_count=await self._storage.events.count_for_profile(profile.id),
            calendar_token=profile.calendar_token,
            recovery_code=recovery_code,
        )
