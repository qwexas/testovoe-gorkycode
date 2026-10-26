"""Маркер `gigachat` для тестов с настоящим GigaChat.

Они ходят в сеть, тратят лимит и нуждаются в ключе, поэтому по умолчанию пропускаются.
Запуск: `GORKY_RUN_GIGACHAT=1 uv run pytest tests/unit/nlu -m gigachat`.
"""

import os

import pytest

RUN_GIGACHAT_ENV = "GORKY_RUN_GIGACHAT"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gigachat: тест с настоящим GigaChat (сеть и ключ)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(RUN_GIGACHAT_ENV) == "1":
        return
    skip_live = pytest.mark.skip(reason=f"настоящий GigaChat; включить: {RUN_GIGACHAT_ENV}=1")
    for item in items:
        if "gigachat" in item.keywords:
            item.add_marker(skip_live)
