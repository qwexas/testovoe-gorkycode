"""Сервис поиска и выбор реализаций поиска в `app.factory` (`SEARCH_BACKEND`)."""

import logging
import sys
from collections.abc import Sequence

import pytest

from app.config import SearchBackend
from app.core.search import SearchService
from app.factory import create_app
from app.search.interfaces import SearchCandidate
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer, SimilarityRanker
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


@pytest.fixture
def search() -> SearchService:
    return SearchService(HashingEmbedder(), LowercaseLemmatizer(), SimilarityRanker())


async def test_index_titles_keeps_order(search: SearchService) -> None:
    indexes = await search.index_titles(["Купить билеты", "Отчёт"])

    assert [index.lemmas for index in indexes] == [["купить", "билеты"], ["отчёт"]]
    assert indexes[1].embedding == await HashingEmbedder().embed_query("Отчёт")


async def test_search_gives_finder_query_vector_and_lemmas(search: SearchService) -> None:
    received: list[tuple[Sequence[float], Sequence[str]]] = []

    async def find_candidates(
        vector: Sequence[float], lemmas: Sequence[str]
    ) -> list[SearchCandidate]:
        received.append((vector, lemmas))
        return [
            SearchCandidate(event_id=1, lemmas=["билеты"], similarity=0.1),
            SearchCandidate(event_id=2, lemmas=["отчёт"], similarity=0.9),
            SearchCandidate(event_id=3, lemmas=["отчёт"], similarity=0.5),
        ]

    ranked = await search.search("Отчёт", find_candidates, limit=5)

    assert received == [(await HashingEmbedder().embed_query("Отчёт"), ["отчёт"])]
    assert [result.event_id for result in ranked] == [2, 3]


async def test_search_without_limit_returns_all_relevant(search: SearchService) -> None:
    async def find_candidates(
        vector: Sequence[float], lemmas: Sequence[str]
    ) -> list[SearchCandidate]:
        return [
            SearchCandidate(event_id=number, lemmas=["отчёт"], similarity=0.9)
            for number in range(60)
        ]

    ranked = await search.search("Отчёт", find_candidates, limit=None)

    assert len(ranked) == 60


def app_search(backend: SearchBackend) -> SearchService:
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, search_backend=backend, load_history_on_startup=False
    )
    service: SearchService = create_app(settings).state.services.search
    return service


async def test_placeholder_backend_uses_placeholders() -> None:
    search = app_search(SearchBackend.PLACEHOLDER)

    assert (await search.index_title("Встречи с Иваном")).lemmas == ["встречи", "с", "иваном"]


async def test_real_backend_falls_back_to_placeholders_without_modules(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "app.search.embedder", None)

    with caplog.at_level(logging.WARNING, logger="app.factory"):
        search = app_search(SearchBackend.REAL)

    assert "заглушки" in caplog.text
    assert (await search.index_title("Встречи с Иваном")).lemmas == ["встречи", "с", "иваном"]
