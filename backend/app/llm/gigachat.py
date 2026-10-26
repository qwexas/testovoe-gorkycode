"""Клиент GigaChat по протоколу `LLMClient`: structured output, очередь, повторы.

- У физлиц один поток, поэтому запросы идут строго по одному (`asyncio.Semaphore(1)`).
- 429, 5xx, таймаут, обрыв связи и ответ не по схеме повторяются (по умолчанию дважды,
  с паузой). Остальное (401, 400, 422) не повторяется. Итог любого сбоя —
  `LLMUnavailableError` с кодом `llm_unavailable`.
- TLS проверяется всегда: системное хранилище, certifi и корневой сертификат Минцифры.
- Ключ не логируется: в логах только модель, время ответа, попытка и тип ошибки.
"""

import asyncio
import json
import logging
import ssl
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import certifi
import httpx
from gigachat import GigaChat
from gigachat.exceptions import RateLimitError, ResponseError
from pydantic import ValidationError

from app.core.enums import ServiceStatus
from app.llm.errors import LLMUnavailableError
from app.llm.interfaces import LLMMessage
from app.llm.settings import GigaChatSettings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HEALTH_CACHE_SECONDS = 60.0
"""Сколько помнить результат проверки живости (и последнего настоящего запроса)."""
HEALTH_TIMEOUT_SECONDS = 5.0
MILLISECONDS_IN_SECOND = 1000.0
CODE_FENCE = "```"


class MalformedResponseError(Exception):
    """Ответ модели — не JSON-объект по схеме: битый JSON, обрезанный ответ, нет полей."""


class ChatTransport(Protocol):
    """Один запрос к API модели. Реализация — `GigaChatTransport` (SDK GigaChat)."""

    async def complete(self, payload: Mapping[str, Any]) -> str:
        """Текст ответа модели на запрос chat/completions."""
        ...

    async def ping(self) -> None:
        """Дешёвый запрос для проверки живости."""
        ...

    async def aclose(self) -> None:
        """Закрывает соединения."""
        ...


def build_ssl_context(root_ca_file: Path | None) -> ssl.SSLContext:
    """Проверка TLS: certifi, системное хранилище и, если задан, корневой сертификат Минцифры.

    Отключать проверку нельзя: без сертификата Минцифры запросы к GigaChat не пройдут.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    if root_ca_file is not None:
        context.load_verify_locations(cafile=root_ca_file)
    return context


class GigaChatTransport:
    """Запросы через официальный SDK `gigachat` (OAuth-токен он обновляет сам)."""

    def __init__(self, settings: GigaChatSettings) -> None:
        credentials = settings.credentials.get_secret_value() if settings.credentials else None
        self._client = GigaChat(
            base_url=settings.base_url,
            auth_url=settings.auth_url,
            credentials=credentials,
            scope=settings.scope,
            model=settings.model,
            timeout=settings.request_timeout_seconds,
            verify_ssl_certs=True,
            ssl_context=build_ssl_context(settings.root_ca_file),
            max_retries=0,
        )

    async def complete(self, payload: Mapping[str, Any]) -> str:
        try:
            completion = await self._client.achat(dict(payload))
        except ValidationError as error:
            # Изредка модель отдаёт пустое сообщение без роли ({"content": ""}), и SDK
            # не может разобрать ответ. Это сбой генерации, а не запроса — повторяем.
            raise MalformedResponseError("SDK не разобрал ответ модели") from error
        if not completion.choices:
            raise MalformedResponseError("в ответе нет вариантов")
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise MalformedResponseError("ответ обрезан по длине")
        if not choice.message.content.strip():
            raise MalformedResponseError("пустой ответ модели")
        return choice.message.content

    async def ping(self) -> None:
        await self._client.aget_models()

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Повторы при временных сбоях."""

    pauses_seconds: tuple[float, ...] = (1.0, 2.0)
    """Пауза перед каждым повтором; число повторов — длина кортежа."""
    max_retry_after_seconds: float = 5.0
    """Потолок для `Retry-After` из ответа 429: дольше пользователь ждать не станет."""
    malformed_retry_temperature: float = 0.5
    """Температура повтора после ответа не по схеме: при почти нулевой температуре модель
    повторила бы тот же зацикленный ответ (например, бесконечное число в поле)."""


@dataclass(frozen=True, slots=True)
class CompletionOptions:
    """Параметры запроса к модели."""

    model: str
    fallback_model: str | None = None
    """Модель для повтора после ответа не по схеме (пустого, битого, обрезанного)."""
    temperature: float = 0.01
    request_timeout_seconds: float = 20.0
    """Таймаут одной попытки."""
    total_timeout_seconds: float = 45.0
    """Всё вместе — очередь, попытки и паузы: ответ должен успеть до таймаута nginx (60 с)."""
    max_output_tokens: int = 256
    """Разбор занимает до ~100 токенов; больше — признак зацикливания, его режем раньше."""
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    @classmethod
    def from_settings(cls, settings: GigaChatSettings) -> "CompletionOptions":
        """Параметры запроса по настройкам `GIGACHAT_*`."""
        return cls(
            model=settings.model,
            fallback_model=settings.fallback_model,
            temperature=settings.temperature,
            request_timeout_seconds=settings.request_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class _HealthMark:
    status: ServiceStatus
    checked_at: float


class GigaChatClient:
    """`LLMClient` для GigaChat. Создание для приложения — `GigaChatClient.from_settings`."""

    def __init__(
        self,
        transport: ChatTransport,
        options: CompletionOptions,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._options = options
        self._clock = clock
        self._queue = asyncio.Semaphore(1)
        self._health: _HealthMark | None = None

    @classmethod
    def from_settings(cls, settings: GigaChatSettings) -> "GigaChatClient":
        """Клиент на SDK GigaChat по настройкам `GIGACHAT_*`."""
        if not settings.is_configured:
            logger.warning("GIGACHAT_CREDENTIALS не задан: разбор реплик будет недоступен")
        return cls(GigaChatTransport(settings), CompletionOptions.from_settings(settings))

    @property
    def model(self) -> str:
        """Имя модели, которой уходят запросы."""
        return self._options.model

    async def complete_json(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Ответ модели по JSON-схеме (strict). Сбой после повторов — `LLMUnavailableError`."""
        payload = self._payload(messages, json_schema)
        required = frozenset(json_schema.get("required", ()))
        try:
            async with asyncio.timeout(self._options.total_timeout_seconds):
                answer = await self._complete_with_retries(payload, required)
        except TimeoutError as error:
            logger.warning("GigaChat %s: общий таймаут разбора истёк", self.model)
            self._remember(ServiceStatus.FAIL)
            raise LLMUnavailableError() from error
        self._remember(ServiceStatus.OK)
        return answer

    async def _complete_with_retries(
        self, payload: Mapping[str, Any], required: frozenset[str]
    ) -> dict[str, Any]:
        error: Exception | None = None
        for attempt, pause in enumerate((0.0, *self._options.retry.pauses_seconds), start=1):
            if error is not None:
                await asyncio.sleep(self._retry_pause(pause, error))
            attempt_payload = self._retry_payload(payload, error)
            try:
                answer = await self._attempt(attempt_payload, required)
            except Exception as failure:
                error = failure
                _log_failure(str(attempt_payload.get("model", self.model)), attempt, failure)
                if not is_retryable(failure):
                    break
            else:
                return answer
        self._remember(ServiceStatus.FAIL)
        raise LLMUnavailableError() from error

    async def check(self) -> ServiceStatus:
        """Жива ли модель — для `/api/health`. Результат помнится `HEALTH_CACHE_SECONDS`.

        Пока идёт разбор реплики, второй запрос не отправляется (один поток):
        возвращается последний известный статус.
        """
        mark = self._health
        if mark is not None and self._clock() - mark.checked_at < HEALTH_CACHE_SECONDS:
            return mark.status
        if self._queue.locked():
            return mark.status if mark is not None else ServiceStatus.UNKNOWN
        status = await self._ping()
        self._remember(status)
        return status

    async def aclose(self) -> None:
        """Закрывает соединения с API."""
        await self._transport.aclose()

    async def _ping(self) -> ServiceStatus:
        try:
            async with self._queue, asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
                await self._transport.ping()
        except Exception as failure:
            logger.warning("GigaChat не отвечает на проверку живости: %s", _describe(failure))
            return ServiceStatus.FAIL
        return ServiceStatus.OK

    def _payload(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "model": self._options.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "temperature": self._options.temperature,
            "max_tokens": self._options.max_output_tokens,
            "response_format": {"type": "json_schema", "schema": dict(json_schema), "strict": True},
        }

    async def _attempt(
        self, payload: Mapping[str, Any], required: frozenset[str]
    ) -> dict[str, Any]:
        async with self._queue:
            started = self._clock()
            async with asyncio.timeout(self._options.request_timeout_seconds):
                content = await self._transport.complete(payload)
            elapsed_ms = (self._clock() - started) * MILLISECONDS_IN_SECOND
        logger.info("GigaChat %s ответил за %.0f мс", payload.get("model"), elapsed_ms)
        return parse_json_object(content, required)

    def _retry_payload(
        self, payload: Mapping[str, Any], error: Exception | None
    ) -> Mapping[str, Any]:
        if not isinstance(error, MalformedResponseError):
            return payload
        retry = {**payload, "temperature": self._options.retry.malformed_retry_temperature}
        if self._options.fallback_model:
            retry["model"] = self._options.fallback_model
        return retry

    def _retry_pause(self, pause: float, error: Exception) -> float:
        if isinstance(error, RateLimitError) and error.retry_after > 0:
            return min(error.retry_after, self._options.retry.max_retry_after_seconds)
        return pause

    def _remember(self, status: ServiceStatus) -> None:
        self._health = _HealthMark(status=status, checked_at=self._clock())


def parse_json_object(content: str, required: frozenset[str]) -> dict[str, Any]:
    """JSON-объект из ответа модели; обёртку ```json … ``` снимает.

    Raises:
        MalformedResponseError: Не JSON, не объект или нет обязательных полей.
    """
    text = content.strip()
    if text.startswith(CODE_FENCE):
        text = text.removeprefix(CODE_FENCE).removeprefix("json").removesuffix(CODE_FENCE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise MalformedResponseError("ответ — не JSON") from error
    if not isinstance(data, dict):
        raise MalformedResponseError("ответ — не JSON-объект")
    missing = required.difference(data)
    if missing:
        raise MalformedResponseError(f"нет полей: {', '.join(sorted(missing))}")
    return data


def is_retryable(error: Exception) -> bool:
    """Временный ли сбой: 429, 5xx, таймаут, обрыв связи, ответ не по схеме."""
    if isinstance(error, TimeoutError | httpx.TransportError | MalformedResponseError):
        return True
    return isinstance(error, ResponseError) and error.status_code in RETRYABLE_STATUS_CODES


def _log_failure(model: str, attempt: int, error: Exception) -> None:
    logger.warning("GigaChat %s, попытка %d: %s", model, attempt, _describe(error))


def _describe(error: Exception) -> str:
    """Тип ошибки и HTTP-статус — без тела ответа и заголовков."""
    if isinstance(error, ResponseError):
        return f"{type(error).__name__} (HTTP {error.status_code})"
    if isinstance(error, MalformedResponseError):
        return f"ответ не по схеме: {error}"
    return type(error).__name__
