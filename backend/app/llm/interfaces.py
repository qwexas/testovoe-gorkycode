"""Интерфейс языковой модели. Реализация (GigaChat) выбирается в конфигурации.

LLM только разбирает реплику в структуру по JSON-схеме; даты, периоды и ответы
пользователю считает код (решения Q24 и «Даты считает код, а не LLM»).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

LLMRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """Сообщение в запросе к модели."""

    role: LLMRole
    content: str


class LLMClient(Protocol):
    """Структурированный разбор текста языковой моделью."""

    async def complete_json(
        self, messages: Sequence[LLMMessage], json_schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Возвращает ответ модели, строго соответствующий `json_schema`.

        Если модель недоступна, реализация бросает `DomainError` с кодом `llm_unavailable`.
        """
        ...
