"""Контракт поиска по смыслу между хранилищем (бэкенд) и ИИ-частью.

Эмбеддинги GigaChat недоступны (402), поэтому векторы считает локальная модель
размерности `EMBEDDING_DIMENSION`. Хранилище отдаёт кандидатов (`SearchCandidate`),
а итоговый порядок и отсечение нерелевантного решает `Ranker`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.enums import EventType

EMBEDDING_DIMENSION = 1024
"""Размерность векторов: под неё создана колонка `events.embedding vector(1024)`."""


class Embedder(Protocol):
    """Превращает тексты в нормированные векторы длины `EMBEDDING_DIMENSION`."""

    @property
    def dimension(self) -> int:
        """Длина каждого вектора."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Векторы записей (названий задач и встреч) в том же порядке, что и `texts`."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Вектор поискового запроса пользователя."""
        ...


class Lemmatizer(Protocol):
    """Приводит слова к начальной форме: «Иваном» → «иван», «договору» → «договор»."""

    def lemmas(self, text: str) -> list[str]:
        """Уникальные значимые леммы текста в порядке появления, без стоп-слов."""
        ...


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """Запись-кандидат, которую хранилище нашло по вектору или по леммам."""

    event_id: int
    lemmas: Sequence[str]
    similarity: float
    """Косинусная близость запроса и записи, от -1 до 1."""
    event_type: EventType | None = None
    """Тип записи — для мягкого бонуса, если разбор запроса назвал тип («встреча с Иваном»)."""


@dataclass(frozen=True, slots=True)
class RankedResult:
    """Запись в итоговой выдаче поиска."""

    event_id: int
    score: float


class Ranker(Protocol):
    """Объединяет близость по смыслу и совпадение лемм, отсекает нерелевантное."""

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        """Лучшие записи по убыванию `score`; пустой список — «ничего похожего нет».

        `preferred_type` — тип из разбора запроса; записи этого типа получают небольшой
        бонус, но записи других типов не отсекаются (LLM может ошибиться с типом).
        """
        ...
