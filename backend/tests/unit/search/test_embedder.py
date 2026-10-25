"""Обёртка над sentence-transformers без загрузки модели: модель подменена."""

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from app.search import embedder as embedder_module
from app.search.embedder import (
    ENCODE_BATCH_SIZE,
    MAX_SEQUENCE_TOKENS,
    EmbeddingDimensionError,
    SentenceTransformerEmbedder,
)
from app.search.interfaces import EMBEDDING_DIMENSION

E5 = "intfloat/multilingual-e5-large"
BGE = "deepvk/USER-bge-m3"


class FakeModel:
    """Запоминает вызовы `encode` и отдаёт векторы нужной длины."""

    def __init__(self, dimension: int = EMBEDDING_DIMENSION) -> None:
        self.dimension = dimension
        self.max_seq_length = 8192
        self.encoded: list[list[str]] = []
        self.encode_options: dict[str, Any] = {}

    def get_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts: Sequence[str], **options: Any) -> NDArray[np.float32]:
        self.encoded.append(list(texts))
        self.encode_options = options
        return np.full((len(texts), self.dimension), 0.5, dtype=np.float32)


class FakeLoader:
    """Подменяет `load_sentence_transformer` и считает загрузки."""

    def __init__(self, model: FakeModel) -> None:
        self.model = model
        self.calls: list[tuple[str, Path | None, str]] = []

    def __call__(self, model_name: str, cache_dir: Path | None, device: str) -> FakeModel:
        self.calls.append((model_name, cache_dir, device))
        return self.model


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch, fake_model: FakeModel) -> FakeLoader:
    fake_loader = FakeLoader(fake_model)
    monkeypatch.setattr(embedder_module, "load_sentence_transformer", fake_loader)
    return fake_loader


async def test_e5_gets_query_and_passage_prefixes(
    loader: FakeLoader, fake_model: FakeModel
) -> None:
    embedder = SentenceTransformerEmbedder(E5, cache_dir=None)

    await embedder.embed_query("встреча с Иваном")
    await embedder.embed_documents(["Встреча с Иваном по CRM"])

    assert fake_model.encoded == [["query: встреча с Иваном"], ["passage: Встреча с Иваном по CRM"]]


async def test_bge_texts_are_encoded_as_is(loader: FakeLoader, fake_model: FakeModel) -> None:
    embedder = SentenceTransformerEmbedder(BGE, cache_dir=None)

    await embedder.embed_query("договор")

    assert fake_model.encoded == [["договор"]]


async def test_unknown_model_is_used_without_prefixes_and_warns(
    loader: FakeLoader, fake_model: FakeModel, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        embedder = SentenceTransformerEmbedder("someone/new-model", cache_dir=None)
    await embedder.embed_query("договор")

    assert fake_model.encoded == [["договор"]]
    assert "someone/new-model" in caplog.text


async def test_vectors_are_normalized_and_batched(
    loader: FakeLoader, fake_model: FakeModel
) -> None:
    embedder = SentenceTransformerEmbedder(BGE, cache_dir=None)

    vectors = await embedder.embed_documents(["акт", "смета", "отчёт"])

    assert len(vectors) == 3
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert fake_model.encode_options["normalize_embeddings"] is True
    assert fake_model.encode_options["batch_size"] == ENCODE_BATCH_SIZE


async def test_empty_documents_do_not_load_model(loader: FakeLoader) -> None:
    embedder = SentenceTransformerEmbedder(BGE, cache_dir=None)

    assert await embedder.embed_documents([]) == []
    assert loader.calls == []


async def test_model_loads_once_with_given_settings(loader: FakeLoader, tmp_path: Path) -> None:
    embedder = SentenceTransformerEmbedder(BGE, cache_dir=tmp_path, device="cpu")

    await asyncio.gather(*(embedder.embed_query(f"запрос {n}") for n in range(5)))
    await embedder.warm_up()

    assert loader.calls == [(BGE, tmp_path, "cpu")]


async def test_sequence_length_is_capped(loader: FakeLoader, fake_model: FakeModel) -> None:
    await SentenceTransformerEmbedder(BGE, cache_dir=None).warm_up()

    assert fake_model.max_seq_length == MAX_SEQUENCE_TOKENS


def test_dimension_is_known_without_loading(loader: FakeLoader) -> None:
    assert SentenceTransformerEmbedder(BGE, cache_dir=None).dimension == EMBEDDING_DIMENSION
    assert loader.calls == []


async def test_wrong_dimension_fails_with_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedder_module, "load_sentence_transformer", FakeLoader(FakeModel(384)))
    embedder = SentenceTransformerEmbedder("intfloat/multilingual-e5-small", cache_dir=None)

    with pytest.raises(EmbeddingDimensionError, match=r"384.*1024"):
        await embedder.embed_query("договор")
