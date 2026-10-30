"""поиск без моделей для тестов и облегчённого режима."""

import hashlib
import math
import re
from collections.abc import Sequence

from app.core.enums import EventType
from app.search.interfaces import EMBEDDING_DIMENSION, RankedResult, SearchCandidate

_WORD = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


class HashingEmbedder:
    """детерминированные векторы из хэшей слов: без модели, для тестов."""

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSION
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSION] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class LowercaseLemmatizer:
    """слова в нижнем регистре без морфологии — заглушка до pymorphy3."""

    def lemmas(self, text: str) -> list[str]:
        return list(dict.fromkeys(word.lower() for word in _WORD.findall(text)))


class SimilarityRanker:
    """сортировка только по близости векторов с простым порогом."""

    def __init__(self, threshold: float = 0.2) -> None:
        self._threshold = threshold

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        relevant = [c for c in candidates if c.similarity >= self._threshold]
        relevant.sort(key=lambda c: c.similarity, reverse=True)
        return [RankedResult(event_id=c.event_id, score=c.similarity) for c in relevant[:limit]]
