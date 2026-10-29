"""Допуск тяжёлых запросов: разбор GigaChat, распознавание Whisper, озвучка Silero.

Модели работают по одному запросу за раз, поэтому без ограничений один пользователь —
или скрипт с пачкой анонимных профилей — занял бы очередь целиком. Здесь:

- ходы одного профиля идут строго по очереди (контекст диалога не теряется), но ждать
  своей очереди может не больше одного хода — остальные получают 429;
- с одного IP не больше `per_client` тяжёлых запросов одновременно и `client_rate` в минуту;
- всего не больше `overall` запросов в работе и в очереди — сверх этого сразу 429,
  а не ожидание до таймаута.

Состояние живёт в памяти процесса: бэкенд запускается одним воркером uvicorn.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from app.core.errors import TooManyAttemptsError
from app.core.rate_limit import SlidingWindowRateLimiter

LOCAL_CLIENT = "local"
"""Ключ клиента, когда IP неизвестен (вызов не из HTTP, тесты)."""
OVERALL_KEY = "*"
BUSY_RETRY_SECONDS = 5
TURN_RETRY_SECONDS = 3


class ServiceBusyError(TooManyAttemptsError):
    """Слишком много тяжёлых запросов в работе — сервис занят."""

    message_template = "Сейчас много запросов. Повторите через несколько секунд."


class TurnInProgressError(TooManyAttemptsError):
    """У профиля уже есть ход в работе и ещё один в очереди."""

    message_template = "Подождите: я ещё отвечаю на предыдущие реплики."


class InFlightLimit:
    """Не больше `limit` одновременных запросов на ключ; сверх — `rejection` сразу."""

    def __init__(
        self,
        limit: int,
        rejection: type[TooManyAttemptsError] = ServiceBusyError,
        retry_after_seconds: int = BUSY_RETRY_SECONDS,
    ) -> None:
        if limit < 1:
            raise ValueError("Лимит должен быть положительным")
        self._limit = limit
        self._rejection = rejection
        self._retry_after = retry_after_seconds
        self._in_flight: dict[str, int] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        """Занимает место для `key` на время блока.

        Raises:
            TooManyAttemptsError: Для `key` уже занято `limit` мест.
        """
        taken = self._in_flight.get(key, 0)
        if taken >= self._limit:
            raise self._rejection(self._retry_after)
        self._in_flight[key] = taken + 1
        try:
            yield
        finally:
            left = self._in_flight[key] - 1
            if left:
                self._in_flight[key] = left
            else:
                del self._in_flight[key]


@dataclass(slots=True)
class _Queue:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    members: int = 0
    """Ход в работе плюс ждущие."""


class ProfileTurns:
    """Ходы одного профиля по очереди — без удержания соединения с БД.

    Второй ход ждёт первого и видит его контекст. Больше `max_members` ходов
    (в работе и в очереди) одного профиля — `TurnInProgressError`.
    """

    def __init__(self, max_members: int = 2) -> None:
        self._max_members = max_members
        self._queues: dict[str, _Queue] = {}

    @asynccontextmanager
    async def turn(self, profile_id: UUID, deadline: float | None = None) -> AsyncIterator[None]:
        """Ждёт очереди профиля до `deadline` (время `loop.time()`) и держит её на время блока.

        Raises:
            TurnInProgressError: Очередь профиля уже полна.
            TimeoutError: Очередь не подошла до `deadline`.
        """
        key = str(profile_id)
        queue = self._queues.setdefault(key, _Queue())
        if queue.members >= self._max_members:
            raise TurnInProgressError(TURN_RETRY_SECONDS)
        queue.members += 1
        try:
            async with asyncio.timeout_at(deadline):
                await queue.lock.acquire()
            try:
                yield
            finally:
                queue.lock.release()
        finally:
            queue.members -= 1
            if not queue.members:
                del self._queues[key]


class ClientRate:
    """Не больше `max_hits` тяжёлых запросов в минуту с одного IP (на все его профили)."""

    def __init__(self, max_hits: int) -> None:
        self._limiter = SlidingWindowRateLimiter(max_hits=max_hits, window_seconds=60)

    def admit(self, client: str) -> None:
        """Учитывает запрос клиента.

        Raises:
            ServiceBusyError: Лимит IP исчерпан.
        """
        decision = self._limiter.hit(client)
        if not decision.allowed:
            raise ServiceBusyError(decision.retry_after_seconds)


class DialogAdmission:
    """Допуск реплик (текст и голос): IP → общая очередь → очередь профиля."""

    def __init__(
        self,
        *,
        overall: int = 12,
        per_client: int = 3,
        client_rate: int = 60,
        turns: ProfileTurns | None = None,
    ) -> None:
        self._overall = InFlightLimit(overall)
        self._per_client = InFlightLimit(per_client)
        self._client_rate = ClientRate(client_rate)
        self._turns = turns or ProfileTurns()

    @asynccontextmanager
    async def enter(
        self, profile_id: UUID, client: str, deadline: float | None = None
    ) -> AsyncIterator[None]:
        """Пропускает реплику, если есть место, и держит её очередь на время блока.

        Raises:
            TooManyAttemptsError: Лимит IP, общей очереди или очереди профиля.
            TimeoutError: Очередь профиля не подошла до `deadline`.
        """
        self._client_rate.admit(client)
        with self._overall.hold(OVERALL_KEY), self._per_client.hold(client):
            async with self._turns.turn(profile_id, deadline):
                yield


class SpeechAdmission:
    """Допуск озвучки: IP → общая очередь синтеза."""

    def __init__(self, *, overall: int = 6, per_client: int = 2, client_rate: int = 90) -> None:
        self._overall = InFlightLimit(overall)
        self._per_client = InFlightLimit(per_client)
        self._client_rate = ClientRate(client_rate)

    @contextmanager
    def enter(self, client: str) -> Iterator[None]:
        """Пропускает озвучку, если есть место.

        Raises:
            ServiceBusyError: Лимит IP или общей очереди.
        """
        self._client_rate.admit(client)
        with self._overall.hold(OVERALL_KEY), self._per_client.hold(client):
            yield
