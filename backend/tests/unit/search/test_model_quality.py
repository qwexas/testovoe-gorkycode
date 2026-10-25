"""Настоящая модель и весь eval-набор: медленно, только с GORKY_RUN_SLOW=1."""

import math

import numpy as np
import pytest

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
    RankingContext,
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


async def test_eval_set_quality_with_default_params(embedder: SentenceTransformerEmbedder) -> None:
    records = load_records(CSV_PATH)
    queries = load_queries(FIXTURE_PATH, records)
    lemmatizer = MorphLemmatizer()
    texts = list(records.values())
    vectors = await embedder.embed_documents(texts)
    corpus = Corpus(
        event_ids=list(records),
        texts=texts,
        lemmas=[lemmatizer.lemmas(text) for text in texts],
        embeddings=np.asarray(vectors, dtype=np.float32),
    )
    prepared = []
    for query in queries:
        vector = np.asarray(await embedder.embed_query(query.text), dtype=np.float32)
        lemmas = lemmatizer.lemmas(query.text)
        prepared.append(
            PreparedQuery(query, lemmas, build_candidates(vector, lemmas, corpus), None)
        )
    context = RankingContext(prepared, LemmaStatistics.from_documents(corpus.lemmas), lemmatizer)

    rankings = context.rank(DEFAULT_RANKING_PARAMS, limit=RESULT_LIMIT, prefer_meetings=False)
    metrics = evaluate(prepared, rankings, DEFAULT_RANKING_PARAMS.threshold)

    assert metrics.recall_at_1 >= MIN_RECALL_AT_1
    assert metrics.no_answer_accuracy == 1.0
