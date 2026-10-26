"""Фикстуры тестов диалога: бизнес-логика на фейковых хранилищах и заготовленных `Intent`.

`FakeIntentParser` играет роль ИИ-части: тест говорит, во что разбирается реплика,
а проверяется только бизнес-логика диалога — без базы, без LLM и без модели.
"""

import pytest

from tests.unit.dialog.support import DialogHarness, new_dialog


@pytest.fixture
def dialog() -> DialogHarness:
    """Диалог нового профиля."""
    return new_dialog()
