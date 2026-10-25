"""Интерфейс модели эмбеддингов для поиска по смыслу.

Эмбеддинги GigaChat недоступны (402), поэтому реализация будет локальной моделью;
размерность вектора определит она, отсюда свойство `dimension`.
"""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Превращает тексты в векторы одинаковой длины."""

    @property
    def dimension(self) -> int:
        """Длина каждого вектора."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Векторы в том же порядке, что и `texts`."""
        ...
