"""контракт поиска по смыслу между хранилищем (бэкенд) и ИИ-частью.

Эмбеддинги GigaChat недоступны (402), поэтому векторы считает локальная модель
размерности `EMBEDDING_DIMENSION`. Хранилище отдаёт кандидатов (`SearchCandidate`),
а итоговый порядок и отсечение нерелевантного решает `Ranker`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.enums import EventType

EMBEDDING_DIMENSION = 1024
"""размерность векторов: под неё создана колонка `events.embedding vector(1024)`."""


class Embedder(Protocol):
    """превращает тексты в нормированные векторы длины `EMBEDDING_DIMENSION`."""

    @property
    def dimension(self) -> int:
        """длина каждого вектора."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """векторы записей (названий задач и встреч) в том же порядке, что и `texts`."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """вектор поискового запроса пользователя."""
        ...


class Lemmatizer(Protocol):
    """приводит слова к начальной форме: «Иваном» → «иван», «договору» → «договор»."""

    def lemmas(self, text: str) -> list[str]:
        """уникальные значимые леммы текста в порядке появления, без стоп-слов."""
        ...


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """запись-кандидат, которую хранилище нашло по вектору или по леммам."""

    event_id: int
    lemmas: Sequence[str]
    similarity: float
    """косинусная близость запроса и записи, от -1 до 1."""
    event_type: EventType | None = None
    """тип записи — для мягкого бонуса, если разбор запроса назвал тип («встреча с Иваном»)."""


@dataclass(frozen=True, slots=True)
class RankedResult:
    """запись в итоговой выдаче поиска."""

    event_id: int
    score: float


class Ranker(Protocol):
    """объединяет близость по смыслу и совпадение лемм, отсекает нерелевантное."""

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        """лучшие записи по убыванию `score`; пустой список — «ничего похожего нет».

        `preferred_type` — тип из разбора запроса; записи этого типа получают небольшой
        бонус, но записи других типов не отсекаются (LLM может ошибиться с типом).
        """
        ...
