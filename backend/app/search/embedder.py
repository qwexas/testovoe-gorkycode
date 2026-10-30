"""эмбеддинги локальной моделью sentence-transformers (эмбеддинги GigaChat недоступны).

Модель грузится лениво — при первом запросе или явном `warm_up()` при старте
приложения — и считает векторы в отдельном потоке, не блокируя event loop.
"""

import asyncio
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.search.interfaces import EMBEDDING_DIMENSION

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

ENCODE_BATCH_SIZE = 32
MAX_SEQUENCE_TOKENS = 256
"""названия записей и запросы короткие; предел защищает от вставки огромного текста."""


@dataclass(frozen=True, slots=True)
class TextPrefixes:
    """префиксы, с которыми модель обучалась различать запросы и документы."""

    query: str = ""
    document: str = ""


NO_PREFIXES = TextPrefixes()
MODEL_PREFIXES: Mapping[str, TextPrefixes] = {
    "deepvk/USER-bge-m3": NO_PREFIXES,
    "BAAI/bge-m3": NO_PREFIXES,
    "intfloat/multilingual-e5-large": TextPrefixes(query="query: ", document="passage: "),
}
"""префиксы по карточкам моделей: bge-m3 и USER-bge-m3 обходятся без них, e5 — нет."""


class EmbeddingDimensionError(RuntimeError):
    """модель выдаёт векторы не той длины, что колонка `events.embedding`."""


def load_sentence_transformer(
    model_name: str, cache_dir: Path | None, device: str
) -> "SentenceTransformer":
    """загружает модель; импорт torch отложен, чтобы не замедлять старт и тесты."""
    from sentence_transformers import SentenceTransformer

    cache_folder = str(cache_dir) if cache_dir is not None else None
    return SentenceTransformer(model_name, device=device, cache_folder=cache_folder)


class SentenceTransformerEmbedder:
    """реализация `Embedder` на sentence-transformers с нормированными векторами.

    `cache_dir` — каталог весов (в репозитории `models/`, он в `.gitignore`);
    `None` — стандартный кэш Hugging Face (`HF_HOME`).
    """

    def __init__(self, model_name: str, cache_dir: Path | None, device: str = "cpu") -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._device = device
        self._prefixes = _prefixes_for(model_name)
        self._model: SentenceTransformer | None = None
        self._load_lock = threading.Lock()

    @property
    def dimension(self) -> int:
        """длина каждого вектора; длину модели проверяет загрузка."""
        return EMBEDDING_DIMENSION

    async def warm_up(self) -> None:
        """загружает модель заранее, чтобы первый запрос пользователя не ждал загрузки."""
        await asyncio.to_thread(self._loaded_model)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """векторы записей (названий задач и встреч) в том же порядке, что и `texts`."""
        if not texts:
            return []
        prefixed = [self._prefixes.document + text for text in texts]
        return await asyncio.to_thread(self._encode, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        """вектор поискового запроса пользователя."""
        [vector] = await asyncio.to_thread(self._encode, [self._prefixes.query + text])
        return vector

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._loaded_model().encode(
            texts,
            batch_size=ENCODE_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        as_lists: list[list[float]] = vectors.tolist()
        return as_lists

    def _loaded_model(self) -> "SentenceTransformer":
        with self._load_lock:
            if self._model is None:
                self._model = self._load_checked_model()
            return self._model

    def _load_checked_model(self) -> "SentenceTransformer":
        logger.info("Загружаю модель эмбеддингов %s на %s", self._model_name, self._device)
        model = load_sentence_transformer(self._model_name, self._cache_dir, self._device)
        dimension = model.get_embedding_dimension()
        if dimension != EMBEDDING_DIMENSION:
            raise EmbeddingDimensionError(
                f"Модель {self._model_name} выдаёт векторы длины {dimension}, а колонка "
                f"events.embedding рассчитана на {EMBEDDING_DIMENSION}. Выберите модель "
                f"размерности {EMBEDDING_DIMENSION} (например, deepvk/USER-bge-m3) "
                "или поменяйте схему БД и пересчитайте эмбеддинги."
            )
        model.max_seq_length = min(model.max_seq_length or MAX_SEQUENCE_TOKENS, MAX_SEQUENCE_TOKENS)
        return model


def _prefixes_for(model_name: str) -> TextPrefixes:
    prefixes = MODEL_PREFIXES.get(model_name)
    if prefixes is None:
        logger.warning(
            "Для модели %s префиксы запроса и документа неизвестны — эмбеддинги без префиксов",
            model_name,
        )
        return NO_PREFIXES
    return prefixes
