"""Настоящий GigaChat: фразы ТЗ и проверка живости. Только с GORKY_RUN_GIGACHAT=1."""

from collections.abc import AsyncIterator

import pytest

from app.core.enums import ServiceStatus
from app.llm.gigachat import GigaChatClient
from app.llm.settings import GigaChatSettings
from app.nlu.parser import LLMIntentParser
from app.search.lemmas import MorphLemmatizer
from scripts.eval_parser import FIXTURE_PATH, compare, load_cases

pytestmark = pytest.mark.gigachat

MAX_TZ_MISSES = 1
"""Модель недетерминирована даже при низкой температуре: одна ошибка на 15 фраз — не поломка."""


@pytest.fixture
async def client() -> AsyncIterator[GigaChatClient]:
    giga = GigaChatClient.from_settings(GigaChatSettings())
    yield giga
    await giga.aclose()


async def test_health_check_reaches_gigachat(client: GigaChatClient) -> None:
    assert await client.check() is ServiceStatus.OK


async def test_tz_phrases_are_understood(client: GigaChatClient) -> None:
    parser = LLMIntentParser(client)
    lemmatizer = MorphLemmatizer()
    misses = []
    for case in [c for c in load_cases(FIXTURE_PATH) if c.group == "tz"]:
        intent = await parser.parse(case.text, case.context)
        checks = compare(intent, case.expected, lemmatizer)
        if not all(checks.values()):
            misses.append((case.text, checks))

    assert len(misses) <= MAX_TZ_MISSES, misses
