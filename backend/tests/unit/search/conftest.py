"""Маркер `slow` для тестов с настоящей моделью эмбеддингов.

Они грузят веса (~1,3 ГБ) и по умолчанию пропускаются. Запуск:
`GORKY_RUN_SLOW=1 uv run pytest tests/unit/search -m slow`.
"""

import os

import pytest

RUN_SLOW_ENV = "GORKY_RUN_SLOW"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: тест с загрузкой модели эмбеддингов")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(RUN_SLOW_ENV) == "1":
        return
    skip_slow = pytest.mark.skip(reason=f"грузит модель; включить: {RUN_SLOW_ENV}=1")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
