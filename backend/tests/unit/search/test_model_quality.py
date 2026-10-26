"""Настоящая модель и весь eval-набор: медленно, только с GORKY_RUN_SLOW=1."""

import asyncio
import math

import numpy as np
import pytest

from app.core.enums import EventType
from app.core.history_source import classify_event_type
from app.search.embedder import SentenceTransformerEmbedder
from app.search.interfaces import EMBEDDING_DIMENSION
from app.search.lemmas import MorphLemmatizer
from app.search.ranking import DEFAULT_RANKING_PARAMS, LemmaStatistics
from scripts.eval_search import (
    CSV_PATH,
    DEFAULT_MODEL,
    FIXTURE_PATH,
    MODELS_DIR,
    RESULT_LIMIT,
    Corpus,
    PreparedQuery,
    Ranking,
    RankingContext,
    TypeMode,
    build_candidates,
    evaluate,
    load_queries,
    load_records,
)

pytestmark = pytest.mark.slow

MIN_RECALL_AT_1 = 0.85
"""Ниже замера (0,907) с запасом: тест ловит поломку, а не колебания на одном запросе."""


@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(DEFAULT_MODEL, MODELS_DIR)


async def test_vectors_are_unit_length_of_contract_size(
    embedder: SentenceTransformerEmbedder,
) -> None:
    [vector] = await embedder.embed_documents(["Встреча с Иваном по CRM"])

    assert len(vector) == EMBEDDING_DIMENSION
    assert math.isclose(float(np.linalg.norm(vector)), 1.0, rel_tol=1e-3)


async def test_query_is_closer_to_matching_record(embedder: SentenceTransformerEmbedder) -> None:
    query = np.asarray(await embedder.embed_query("Когда я звонил Ивану?"))
    call, estimate = np.asarray(
        await embedder.embed_documents(["Позвонить Иваном", "Подготовить смету"])
    )

    assert query @ call > query @ estimate


RankingInputs = tuple[list[PreparedQuery], Corpus, LemmaStatistics, MorphLemmatizer]


@pytest.fixture(scope="module")
def ranking_inputs(embedder: SentenceTransformerEmbedder) -> RankingInputs:
    """Векторы 1000 записей и запросов считаются один раз на модуль."""
    return asyncio.run(_prepare_ranking_inputs(embedder))


async def _prepare_ranking_inputs(embedder: SentenceTransformerEmbedder) -> RankingInputs:
    records = load_records(CSV_PATH)
    queries = load_queries(FIXTURE_PATH, records)
    lemmatizer = MorphLemmatizer()
    corpus = Corpus.from_records(
        records, lemmatizer, await embedder.embed_documents(list(records.values()))
    )
    prepared = []
    for query in queries:
        vector = np.asarray(await embedder.embed_query(query.text), dtype=np.float32)
        lemmas = lemmatizer.lemmas(query.text)
        prepared.append(
            PreparedQuery(query, lemmas, build_candidates(vector, lemmas, corpus), None)
        )
    return prepared, corpus, LemmaStatistics.from_documents(corpus.lemmas), lemmatizer


def rank(inputs: RankingInputs, type_mode: TypeMode) -> tuple[list[PreparedQuery], list[Ranking]]:
    prepared, _, statistics, lemmatizer = inputs
    context = RankingContext(prepared, statistics, lemmatizer, type_mode)
    return prepared, context.rank(DEFAULT_RANKING_PARAMS, limit=RESULT_LIMIT)


def test_eval_set_quality_with_default_params(ranking_inputs: RankingInputs) -> None:
    prepared, rankings = rank(ranking_inputs, TypeMode.IGNORE)

    metrics = evaluate(prepared, rankings, DEFAULT_RANKING_PARAMS.threshold)

    assert metrics.recall_at_1 >= MIN_RECALL_AT_1
    assert metrics.no_answer_accuracy == 1.0


def test_type_bonus_does_not_hurt_eval_set(ranking_inputs: RankingInputs) -> None:
    prepared, plain = rank(ranking_inputs, TypeMode.IGNORE)
    _, with_type = rank(ranking_inputs, TypeMode.BONUS)
    threshold = DEFAULT_RANKING_PARAMS.threshold

    plain_metrics = evaluate(prepared, plain, threshold)
    typed_metrics = evaluate(prepared, with_type, threshold)

    assert typed_metrics.recall_at_1 >= plain_metrics.recall_at_1
    assert typed_metrics.no_answer_accuracy == 1.0


def test_meeting_type_puts_meetings_with_ivan_first(ranking_inputs: RankingInputs) -> None:
    prepared, rankings = rank(ranking_inputs, TypeMode.BONUS)
    corpus = ranking_inputs[1]

    top = top_texts(prepared, rankings, corpus, "Когда у меня была встреча с Иваном?", count=3)

    assert "Отправить итоги встречи Иваном" not in top
    assert all(classify_event_type(text) is EventType.MEETING for text in top), top


def test_meeting_results_task_still_found(ranking_inputs: RankingInputs) -> None:
    prepared, rankings = rank(ranking_inputs, TypeMode.BONUS)
    corpus = ranking_inputs[1]

    [top] = top_texts(prepared, rankings, corpus, "Итоги встречи для Максима", count=1)

    assert top == "Отправить итоги встречи Максимом"


def top_texts(
    prepared: list[PreparedQuery], rankings: list[Ranking], corpus: Corpus, query: str, count: int
) -> list[str]:
    """Первые `count` разных названий в выдаче на запрос `query`."""
    text_by_id = dict(zip(corpus.event_ids, corpus.texts, strict=True))
    [ranking] = [r for item, r in zip(prepared, rankings, strict=True) if item.query.text == query]
    texts = list(dict.fromkeys(text_by_id[event_id] for event_id, _ in ranking))
    return texts[:count]
