"""Поиск записей по смыслу и поисковый индекс названий.

Сервис не знает ни про HTTP, ни про таблицы: векторы и леммы считают `Embedder` и
`Lemmatizer`, кандидатов из хранилища приносит переданная функция, итоговый порядок
решает `Ranker`. Реализации выбираются в `app.factory`.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.search.interfaces import Embedder, Lemmatizer, RankedResult, Ranker, SearchCandidate

CandidateFinder = Callable[[Sequence[float], Sequence[str]], Awaitable[list[SearchCandidate]]]
"""Достаёт кандидатов по вектору запроса и его леммам: `(vector, lemmas) -> candidates`."""


@dataclass(frozen=True, slots=True)
class TitleIndex:
    """Поисковый индекс названия записи: вектор и значимые леммы."""

    embedding: list[float]
    lemmas: list[str]


class SearchService:
    """Индексирует названия записей и ищет записи по запросу пользователя."""

    def __init__(self, embedder: Embedder, lemmatizer: Lemmatizer, ranker: Ranker) -> None:
        self._embedder = embedder
        self._lemmatizer = lemmatizer
        self._ranker = ranker

    async def index_title(self, title: str) -> TitleIndex:
        """Индекс одного названия — при создании записи и смене названия."""
        [index] = await self.index_titles([title])
        return index

    async def index_titles(self, titles: Sequence[str]) -> list[TitleIndex]:
        """Индексы названий в том же порядке; векторы считаются одним пакетом."""
        embeddings = await self._embedder.embed_documents(titles)
        return [
            TitleIndex(embedding=embedding, lemmas=self._lemmatizer.lemmas(title))
            for title, embedding in zip(titles, embeddings, strict=True)
        ]

    async def search(
        self, query: str, find_candidates: CandidateFinder, *, limit: int
    ) -> list[RankedResult]:
        """Лучшие записи по запросу, по убыванию релевантности; пусто — ничего похожего."""
        query_vector = await self._embedder.embed_query(query)
        query_lemmas = self._lemmatizer.lemmas(query)
        candidates = await find_candidates(query_vector, query_lemmas)
        return self._ranker.rank(query_lemmas, candidates, limit=limit)
