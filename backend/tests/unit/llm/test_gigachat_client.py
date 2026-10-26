"""`GigaChatClient` без сети: повторы, ошибки, очередь, проверка живости."""

import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from gigachat.exceptions import AuthenticationError, RateLimitError, ServerError

from app.core.enums import ServiceStatus
from app.core.errors import ErrorCode
from app.llm.errors import LLMUnavailableError
from app.llm.gigachat import (
    CompletionOptions,
    GigaChatClient,
    MalformedResponseError,
    RetryPolicy,
    build_ssl_context,
    parse_json_object,
)
from app.llm.interfaces import LLMMessage
from app.llm.settings import BUNDLED_ROOT_CA, GigaChatSettings

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"action": {"type": "string"}, "title": {"type": "string"}},
    "required": ["action"],
}
MESSAGES = [LLMMessage("system", "правила"), LLMMessage("user", "реплика")]
GOOD_ANSWER = json.dumps({"action": "create", "title": "Купить билеты"})
API_URL = "https://api.giga.chat/v1/chat/completions"
NO_PAUSES = RetryPolicy(pauses_seconds=(0.0, 0.0))

Outcome = str | Exception


class ScriptedTransport:
    """Отвечает по сценарию: строка — ответ модели, исключение — сбой."""

    def __init__(self, *outcomes: Outcome, delay_seconds: float = 0.0) -> None:
        self._outcomes = list(outcomes)
        self._delay = delay_seconds
        self.payloads: list[Mapping[str, Any]] = []
        self.pings = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed = False

    async def complete(self, payload: Mapping[str, Any]) -> str:
        self.payloads.append(payload)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self._delay)
            outcome = self._outcomes.pop(0)
        finally:
            self.in_flight -= 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def ping(self) -> None:
        self.pings += 1
        outcome = self._outcomes.pop(0) if self._outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome

    async def aclose(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(
    transport: ScriptedTransport,
    *,
    timeout_seconds: float = 20.0,
    clock: FakeClock | None = None,
) -> GigaChatClient:
    options = CompletionOptions(
        model="GigaChat-2-Pro", request_timeout_seconds=timeout_seconds, retry=NO_PAUSES
    )
    return GigaChatClient(transport, options, clock or FakeClock())


def rate_limited(retry_after: str = "0") -> RateLimitError:
    return RateLimitError(API_URL, 429, b"", httpx.Headers({"retry-after": retry_after}))


def server_error() -> ServerError:
    return ServerError(API_URL, 503, b"", None)


async def test_returns_json_object_from_model() -> None:
    client = make_client(ScriptedTransport(GOOD_ANSWER))

    assert await client.complete_json(MESSAGES, SCHEMA) == {
        "action": "create",
        "title": "Купить билеты",
    }


async def test_requests_strict_json_schema_with_low_temperature() -> None:
    transport = ScriptedTransport(GOOD_ANSWER)

    await make_client(transport).complete_json(MESSAGES, SCHEMA)

    [payload] = transport.payloads
    assert payload["model"] == "GigaChat-2-Pro"
    assert payload["response_format"] == {"type": "json_schema", "schema": SCHEMA, "strict": True}
    assert payload["temperature"] < 0.1
    assert payload["messages"] == [
        {"role": "system", "content": "правила"},
        {"role": "user", "content": "реплика"},
    ]


async def test_rate_limit_is_retried() -> None:
    transport = ScriptedTransport(rate_limited(), GOOD_ANSWER)

    answer = await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert answer["action"] == "create"
    assert len(transport.payloads) == 2


async def test_server_error_is_retried() -> None:
    transport = ScriptedTransport(server_error(), server_error(), GOOD_ANSWER)

    await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert len(transport.payloads) == 3


async def test_lost_connection_is_retried() -> None:
    transport = ScriptedTransport(httpx.ConnectError("нет связи"), GOOD_ANSWER)

    await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert len(transport.payloads) == 2


async def test_timeouts_exhaust_retries_into_llm_unavailable() -> None:
    transport = ScriptedTransport(GOOD_ANSWER, GOOD_ANSWER, GOOD_ANSWER, delay_seconds=0.05)
    client = make_client(transport, timeout_seconds=0.01)

    with pytest.raises(LLMUnavailableError) as raised:
        await client.complete_json(MESSAGES, SCHEMA)

    assert raised.value.code is ErrorCode.LLM_UNAVAILABLE
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert len(transport.payloads) == 3


async def test_total_timeout_cuts_retries_short() -> None:
    transport = ScriptedTransport(server_error(), GOOD_ANSWER)
    options = CompletionOptions(
        model="GigaChat-2-Pro",
        total_timeout_seconds=0.05,
        retry=RetryPolicy(pauses_seconds=(1.0,)),
    )
    client = GigaChatClient(transport, options, FakeClock())

    with pytest.raises(LLMUnavailableError) as raised:
        await client.complete_json(MESSAGES, SCHEMA)

    assert isinstance(raised.value.__cause__, TimeoutError)
    assert len(transport.payloads) == 1
    assert await client.check() is ServiceStatus.FAIL


async def test_broken_json_is_retried() -> None:
    transport = ScriptedTransport('{"action": "cre', GOOD_ANSWER)

    answer = await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert answer["action"] == "create"


async def test_retry_after_broken_answer_uses_higher_temperature() -> None:
    transport = ScriptedTransport("не json", GOOD_ANSWER)

    await make_client(transport).complete_json(MESSAGES, SCHEMA)

    first, second = transport.payloads
    assert second["temperature"] > first["temperature"]


async def test_retry_after_broken_answer_switches_to_fallback_model() -> None:
    transport = ScriptedTransport("", GOOD_ANSWER)
    options = CompletionOptions(
        model="GigaChat-2-Pro", fallback_model="GigaChat-2-Max", retry=NO_PAUSES
    )

    answer = await GigaChatClient(transport, options, FakeClock()).complete_json(MESSAGES, SCHEMA)

    first, second = transport.payloads
    assert (first["model"], second["model"]) == ("GigaChat-2-Pro", "GigaChat-2-Max")
    assert answer["action"] == "create"


async def test_retry_after_rate_limit_keeps_model() -> None:
    transport = ScriptedTransport(rate_limited(), GOOD_ANSWER)
    options = CompletionOptions(
        model="GigaChat-2-Pro", fallback_model="GigaChat-2-Max", retry=NO_PAUSES
    )

    await GigaChatClient(transport, options, FakeClock()).complete_json(MESSAGES, SCHEMA)

    assert [payload["model"] for payload in transport.payloads] == ["GigaChat-2-Pro"] * 2


async def test_retry_after_rate_limit_keeps_temperature() -> None:
    transport = ScriptedTransport(rate_limited(), GOOD_ANSWER)

    await make_client(transport).complete_json(MESSAGES, SCHEMA)

    first, second = transport.payloads
    assert second["temperature"] == first["temperature"]


async def test_always_broken_json_becomes_llm_unavailable() -> None:
    transport = ScriptedTransport("[]", "{}", '```json\n{"title": 1}\n```')

    with pytest.raises(LLMUnavailableError) as raised:
        await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert isinstance(raised.value.__cause__, MalformedResponseError)


async def test_authentication_error_is_not_retried() -> None:
    transport = ScriptedTransport(AuthenticationError(API_URL, 401, b"", None), GOOD_ANSWER)

    with pytest.raises(LLMUnavailableError):
        await make_client(transport).complete_json(MESSAGES, SCHEMA)

    assert len(transport.payloads) == 1


async def test_unexpected_error_becomes_llm_unavailable() -> None:
    transport = ScriptedTransport(RuntimeError("сбой SDK"))

    with pytest.raises(LLMUnavailableError):
        await make_client(transport).complete_json(MESSAGES, SCHEMA)


async def test_requests_go_one_at_a_time() -> None:
    transport = ScriptedTransport(*[GOOD_ANSWER] * 4, delay_seconds=0.01)
    client = make_client(transport)

    await asyncio.gather(*(client.complete_json(MESSAGES, SCHEMA) for _ in range(4)))

    assert transport.max_in_flight == 1


def test_json_in_code_fence_is_accepted() -> None:
    assert parse_json_object('```json\n{"action": "list"}\n```', frozenset({"action"})) == {
        "action": "list"
    }


def test_missing_required_field_is_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        parse_json_object('{"title": "x"}', frozenset({"action"}))


async def test_health_check_pings_once_and_caches() -> None:
    clock = FakeClock()
    transport = ScriptedTransport()
    client = make_client(transport, clock=clock)

    assert await client.check() is ServiceStatus.OK
    clock.now += 30
    assert await client.check() is ServiceStatus.OK
    assert transport.pings == 1


async def test_health_check_repeats_after_cache_expires() -> None:
    clock = FakeClock()
    transport = ScriptedTransport("ok", server_error())
    client = make_client(transport, clock=clock)

    assert await client.check() is ServiceStatus.OK
    clock.now += 61
    assert await client.check() is ServiceStatus.FAIL


async def test_successful_request_counts_as_health() -> None:
    transport = ScriptedTransport(GOOD_ANSWER)
    client = make_client(transport)

    await client.complete_json(MESSAGES, SCHEMA)

    assert await client.check() is ServiceStatus.OK
    assert transport.pings == 0


async def test_failed_request_counts_as_health() -> None:
    client = make_client(ScriptedTransport(AuthenticationError(API_URL, 401, b"", None)))

    with pytest.raises(LLMUnavailableError):
        await client.complete_json(MESSAGES, SCHEMA)

    assert await client.check() is ServiceStatus.FAIL


async def test_health_check_does_not_wait_for_busy_model() -> None:
    transport = ScriptedTransport(GOOD_ANSWER, delay_seconds=0.05)
    client = make_client(transport)

    request = asyncio.create_task(client.complete_json(MESSAGES, SCHEMA))
    await asyncio.sleep(0.01)

    assert await client.check() is ServiceStatus.UNKNOWN
    assert transport.pings == 0
    await request


async def test_close_closes_transport() -> None:
    transport = ScriptedTransport()

    await make_client(transport).aclose()

    assert transport.closed


def test_ssl_context_trusts_russian_root_and_verifies() -> None:
    context = build_ssl_context(BUNDLED_ROOT_CA)

    common_names = {
        dict(item[0] for item in cert["subject"]).get("commonName")
        for cert in context.get_ca_certs()
    }
    assert "Russian Trusted Root CA" in common_names
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname


def test_settings_hide_credentials() -> None:
    settings = GigaChatSettings(_env_file=None, credentials="секретный-ключ")

    assert "секретный-ключ" not in repr(settings)
    assert "секретный-ключ" not in str(settings.model_dump())
    assert settings.is_configured


def test_settings_without_credentials_are_not_configured() -> None:
    assert not GigaChatSettings(_env_file=None, credentials=None).is_configured


async def test_client_builds_from_settings_without_network() -> None:
    settings = GigaChatSettings(_env_file=None, credentials=None, model="GigaChat-3-Ultra")

    client = GigaChatClient.from_settings(settings)

    assert client.model == "GigaChat-3-Ultra"
    await client.aclose()
