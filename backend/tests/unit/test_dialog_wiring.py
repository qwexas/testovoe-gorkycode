"""Выбор разбора реплик в `app.factory` (`LLM_BACKEND`) и проверка LLM в `/api/health`."""

import logging
import sys

import httpx
import pytest

from app.config import LLMBackend
from app.core.enums import ServiceStatus
from app.core.health import check_health
from app.factory import create_app
from app.llm.errors import LLMUnavailableError
from app.nlu.interfaces import DialogContext, IntentParser
from app.storage.database import Database
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings
from tests.unit.dialog.support import NOW


def app_parser(backend: LLMBackend) -> IntentParser:
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, llm_backend=backend, load_history_on_startup=False
    )
    parser: IntentParser = create_app(settings).state.services.intent_parser
    return parser


async def assert_unavailable(parser: IntentParser) -> None:
    with pytest.raises(LLMUnavailableError):
        await parser.parse("Привет", DialogContext(now=NOW))


async def test_disabled_backend_answers_llm_unavailable() -> None:
    await assert_unavailable(app_parser(LLMBackend.DISABLED))


async def test_missing_modules_fall_back_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "app.nlu.parser", None)

    with caplog.at_level(logging.WARNING, logger="app.factory"):
        parser = app_parser(LLMBackend.GIGACHAT)

    assert "Разбор реплик недоступен" in caplog.text
    await assert_unavailable(parser)


async def test_missing_credentials_fall_back_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "")

    with caplog.at_level(logging.WARNING, logger="app.factory"):
        parser = app_parser(LLMBackend.GIGACHAT)

    assert "GIGACHAT_CREDENTIALS" in caplog.text
    await assert_unavailable(parser)


def test_configured_gigachat_builds_llm_parser_and_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.gigachat import GigaChatClient
    from app.nlu.parser import LLMIntentParser

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "test-credentials-not-used")
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, llm_backend=LLMBackend.GIGACHAT, load_history_on_startup=False
    )

    services = create_app(settings).state.services

    assert isinstance(services.intent_parser, LLMIntentParser)
    assert isinstance(services.llm_probe, GigaChatClient)


class FixedProbe:
    def __init__(self, status: ServiceStatus) -> None:
        self._status = status

    async def check(self) -> ServiceStatus:
        return self._status


@pytest.mark.parametrize("status", [ServiceStatus.OK, ServiceStatus.FAIL])
async def test_health_reports_llm_probe(status: ServiceStatus) -> None:
    database = Database(UNREACHABLE_DATABASE_URL)

    report = await check_health(database, FixedProbe(status))

    assert (report.db, report.llm) == (ServiceStatus.FAIL, status)
    await database.dispose()


async def test_health_without_llm_is_unknown(offline_client: httpx.AsyncClient) -> None:
    response = await offline_client.get("/api/health")

    assert response.json()["checks"]["llm"] == "unknown"
