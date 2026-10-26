"""Офлайн-оценка поиска по смыслу: модель эмбеддингов + HybridRanker, без БД.

Прогоняет `tests/fixtures/search_eval.json` по 1000 записям из CSV тестового задания:
эмбеддит записи, для каждого запроса берёт кандидатов так же, как хранилище
(top-100 по косинусу плюс записи с общими леммами), ранжирует и считает метрики —
по записям и по уникальным названиям (в CSV 376 названий на 1000 записей).

Запуск из каталога backend/:
    uv run python -m scripts.eval_search                         # модель и веса по умолчанию
    uv run python -m scripts.eval_search --model BAAI/bge-m3 --tune
    uv run python -m scripts.eval_search --prefer-meetings --show-failures
    uv run python -m scripts.eval_search --type-bonus --tune-type    # вес бонуса за тип
"""

import argparse
import asyncio
import csv
import json
import math
import resource
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.core.enums import EventType
from app.core.history_source import classify_event_type
from app.search.embedder import SentenceTransformerEmbedder
from app.search.interfaces import RankedResult, SearchCandidate
from app.search.lemmas import MorphLemmatizer
from app.search.ranking import DEFAULT_RANKING_PARAMS, HybridRanker, LemmaStatistics, RankingParams

DESCRIPTION = "Офлайн-оценка поиска по смыслу на eval-наборе"

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "GORKYCODE тестовое" / "voice_assistant_events_1000.csv"
FIXTURE_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "search_eval.json"
MODELS_DIR = REPO_ROOT / "models"
DEFAULT_MODEL = "deepvk/USER-bge-m3"

COSINE_CANDIDATES = 100
RESULT_LIMIT = 10
GROUPING_LIMIT = 50
"""Сколько записей берём, чтобы после группировки по названию осталось `RESULT_LIMIT` групп."""
RECALL_DEPTH = 5
MEETING_INTENT = "meeting"

LEXICAL_WEIGHT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
NAME_WEIGHT_GRID = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25)
HEAD_WEIGHT_GRID = (0.0, 0.025, 0.05, 0.1, 0.15)
THRESHOLD_GRID = tuple(round(0.20 + 0.01 * step, 2) for step in range(76))
PLATEAU_TOLERANCE = 0.005
"""Пороги, у которых цель хуже максимума не больше чем на четверть запроса, считаем равными."""
TYPE_WEIGHT_GRID = (0.0, 0.025, 0.05, 0.075, 0.1, 0.125, 0.15, 0.2)
CROSS_VALIDATION_FOLDS = 4
FAILURE_TEXTS_SHOWN = 3

UNTUNED = -math.inf
SECONDS_TO_MS = 1000.0
BYTES_IN_MIB = 1024 * 1024
KIB_IN_MIB = 1024


class TypeMode(StrEnum):
    """Как учитывать тип записи из разбора запроса (`intent_type` в eval-наборе)."""

    IGNORE = "ignore"
    """Тип не учитывается."""
    FILTER = "filter"
    """Сначала только записи этого типа, при пустой выдаче — все (жёсткий фильтр бэкенда)."""
    BONUS = "bonus"
    """`HybridRanker.rank(..., preferred_type=...)`: мягкий бонус `type_weight`."""


@dataclass(frozen=True, slots=True)
class EvalQuery:
    text: str
    category: str
    intent_type: str | None
    relevant_ids: frozenset[int]

    @property
    def expects_answer(self) -> bool:
        return bool(self.relevant_ids)

    @property
    def preferred_type(self) -> EventType | None:
        return EventType(self.intent_type) if self.intent_type else None


@dataclass(frozen=True, slots=True)
class Corpus:
    event_ids: list[int]
    texts: list[str]
    lemmas: list[list[str]]
    embeddings: NDArray[np.float32]
    event_types: list[EventType]

    @classmethod
    def from_records(
        cls,
        records: dict[int, str],
        lemmatizer: MorphLemmatizer,
        vectors: Sequence[Sequence[float]],
    ) -> "Corpus":
        """Записи CSV с леммами, векторами и типом по правилу бэкенда (`classify_event_type`)."""
        texts = list(records.values())
        return cls(
            event_ids=list(records),
            texts=texts,
            lemmas=[lemmatizer.lemmas(text) for text in texts],
            embeddings=np.asarray(vectors, dtype=np.float32),
            event_types=[classify_event_type(text) for text in texts],
        )

    def only(self, event_type: EventType) -> "Corpus":
        """Подмножество записей одного типа — как хранилище с фильтром по типу."""
        indexes = [i for i, kind in enumerate(self.event_types) if kind is event_type]
        return Corpus(
            event_ids=[self.event_ids[i] for i in indexes],
            texts=[self.texts[i] for i in indexes],
            lemmas=[self.lemmas[i] for i in indexes],
            embeddings=self.embeddings[indexes],
            event_types=[self.event_types[i] for i in indexes],
        )


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    query: EvalQuery
    lemmas: list[str]
    candidates: list[SearchCandidate]
    meeting_candidates: list[SearchCandidate] | None
    """Кандидаты среди встреч — для запросов, где разбор LLM поставил тип «встреча»."""


@dataclass(frozen=True, slots=True)
class Metrics:
    recall_at_1: float
    recall_at_5: float
    mrr: float
    no_answer_accuracy: float
    empty_on_answerable: int
    objective: float


@dataclass(frozen=True, slots=True)
class Timings:
    model_load_s: float
    corpus_embedding_s: float
    query_latencies_ms: list[float]
    peak_rss_after_load_mib: float
    peak_rss_after_corpus_mib: float


Ranking = list[tuple[int, float]]
ScoredGrid = dict[RankingParams, list[Ranking]]


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="имя модели на Hugging Face")
    parser.add_argument("--cache-dir", type=Path, default=MODELS_DIR, help="каталог весов")
    parser.add_argument("--device", default="cpu", help="cpu (как на сервере) или mps/cuda")
    parser.add_argument("--tune", action="store_true", help="подобрать веса и порог по сетке")
    type_mode = parser.add_mutually_exclusive_group()
    type_mode.add_argument(
        "--prefer-meetings",
        action="store_true",
        help="для запросов с типом «встреча» сначала искать среди встреч, потом среди всех",
    )
    type_mode.add_argument(
        "--type-bonus",
        action="store_true",
        help="тип из запроса — мягкий бонус ранжирования (preferred_type)",
    )
    parser.add_argument(
        "--tune-type", action="store_true", help="подобрать вес бонуса за тип и порог"
    )
    parser.add_argument("--show-failures", action="store_true", help="разбор ошибок по запросам")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    records = load_records(CSV_PATH)
    queries = load_queries(FIXTURE_PATH, records)
    lemmatizer = MorphLemmatizer()
    embedder = SentenceTransformerEmbedder(args.model, args.cache_dir, args.device)

    rss_before = _peak_rss_mib()
    started = time.perf_counter()
    await embedder.warm_up()
    model_load_s = time.perf_counter() - started
    rss_after_load = _peak_rss_mib()

    corpus, corpus_embedding_s = await _embed_corpus(records, embedder, lemmatizer)
    rss_after_corpus = _peak_rss_mib()
    prepared, latencies = await _prepare_queries(queries, corpus, embedder, lemmatizer)
    timings = Timings(
        model_load_s=model_load_s,
        corpus_embedding_s=corpus_embedding_s,
        query_latencies_ms=latencies,
        peak_rss_after_load_mib=rss_after_load - rss_before,
        peak_rss_after_corpus_mib=rss_after_corpus - rss_before,
    )

    type_mode = _type_mode(args)
    context = RankingContext(
        prepared, LemmaStatistics.from_documents(corpus.lemmas), lemmatizer, type_mode
    )
    print(f"Модель: {args.model} ({args.device}); запросов: {len(queries)}; тип: {type_mode}")
    params = DEFAULT_RANKING_PARAMS
    if args.tune:
        params = _tune_and_report(context)
    if args.tune_type:
        params = _tune_type_and_report(context, params)
    _report(context, params, corpus, args)
    _print_timings(timings)


def _type_mode(args: argparse.Namespace) -> TypeMode:
    if args.prefer_meetings:
        return TypeMode.FILTER
    if args.type_bonus:
        return TypeMode.BONUS
    return TypeMode.IGNORE


def load_records(path: Path) -> dict[int, str]:
    """Записи CSV тестового задания: id → текст."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {int(row["id"]): row["text"] for row in csv.DictReader(file)}


def load_queries(path: Path, records: dict[int, str]) -> list[EvalQuery]:
    """Запросы eval-набора; проверяет, что ожидаемые id совпадают с подписанными текстами."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = []
    for item in raw["queries"]:
        relevant_ids = frozenset(item["relevant_ids"])
        actual_texts = {records[event_id] for event_id in relevant_ids}
        if actual_texts != set(item["relevant_texts"]):
            raise ValueError(f"relevant_ids и relevant_texts расходятся: {item['query']!r}")
        queries.append(
            EvalQuery(item["query"], item["category"], item["intent_type"], relevant_ids)
        )
    return queries


async def _embed_corpus(
    records: dict[int, str], embedder: SentenceTransformerEmbedder, lemmatizer: MorphLemmatizer
) -> tuple[Corpus, float]:
    started = time.perf_counter()
    vectors = await embedder.embed_documents(list(records.values()))
    elapsed = time.perf_counter() - started
    return Corpus.from_records(records, lemmatizer, vectors), elapsed


async def _prepare_queries(
    queries: Sequence[EvalQuery],
    corpus: Corpus,
    embedder: SentenceTransformerEmbedder,
    lemmatizer: MorphLemmatizer,
) -> tuple[list[PreparedQuery], list[float]]:
    meetings = corpus.only(EventType.MEETING)
    await embedder.embed_query("прогрев")
    prepared, latencies = [], []
    for query in queries:
        started = time.perf_counter()
        vector = np.asarray(await embedder.embed_query(query.text), dtype=np.float32)
        latencies.append((time.perf_counter() - started) * SECONDS_TO_MS)
        lemmas = lemmatizer.lemmas(query.text)
        meeting_candidates = (
            build_candidates(vector, lemmas, meetings)
            if query.intent_type == MEETING_INTENT
            else None
        )
        candidates = build_candidates(vector, lemmas, corpus)
        prepared.append(PreparedQuery(query, lemmas, candidates, meeting_candidates))
    return prepared, latencies


def build_candidates(
    query_vector: NDArray[np.float32], query_lemmas: Sequence[str], corpus: Corpus
) -> list[SearchCandidate]:
    """Как хранилище: top-100 по косинусу плюс все записи хотя бы с одной общей леммой."""
    similarities = corpus.embeddings @ query_vector
    nearest_count = min(COSINE_CANDIDATES, len(similarities) - 1)
    nearest = np.argpartition(-similarities, nearest_count)[:nearest_count]
    lemma_set = set(query_lemmas)
    sharing_lemmas = [i for i, lemmas in enumerate(corpus.lemmas) if lemma_set.intersection(lemmas)]
    indexes = sorted({*nearest.tolist(), *sharing_lemmas})
    return [
        SearchCandidate(
            event_id=corpus.event_ids[i],
            lemmas=corpus.lemmas[i],
            similarity=float(similarities[i]),
            event_type=corpus.event_types[i],
        )
        for i in indexes
    ]


@dataclass(frozen=True, slots=True)
class RankingContext:
    """Подготовленные запросы и всё, что нужно `HybridRanker`."""

    prepared: Sequence[PreparedQuery]
    statistics: LemmaStatistics
    lemmatizer: MorphLemmatizer
    type_mode: TypeMode = TypeMode.IGNORE

    def rank_untuned(self, params: RankingParams) -> list[Ranking]:
        """Выдача без порога и без типа: порог применяется при подсчёте метрик.

        Тип записи не учитывается: порог `HybridRanker` сравнивает с оценкой без бонуса
        за тип, поэтому и подбор порога идёт по ней. Перебор порогов так дёшев.
        """
        ranker = HybridRanker(self.statistics, self.lemmatizer, replace(params, threshold=UNTUNED))
        return [
            _as_ranking(ranker.rank(item.lemmas, item.candidates, limit=RESULT_LIMIT))
            for item in self.prepared
        ]

    def rank(self, params: RankingParams, *, limit: int) -> list[Ranking]:
        """Выдача с порогом, как в приложении; тип записи — по `type_mode`.

        `FILTER`: запрос с типом «встреча» ищется среди встреч, а если там ничего не нашлось —
        среди всех записей. `BONUS`: тип передаётся ранжированию как `preferred_type`.
        """
        ranker = HybridRanker(self.statistics, self.lemmatizer, params)
        return [_as_ranking(self._rank_one(ranker, item, limit)) for item in self.prepared]

    def _rank_one(
        self, ranker: HybridRanker, item: PreparedQuery, limit: int
    ) -> list[RankedResult]:
        if self.type_mode is TypeMode.BONUS:
            preferred = item.query.preferred_type
            return ranker.rank(item.lemmas, item.candidates, limit=limit, preferred_type=preferred)
        ranked: list[RankedResult] = []
        if self.type_mode is TypeMode.FILTER and item.meeting_candidates is not None:
            ranked = ranker.rank(item.lemmas, item.meeting_candidates, limit=limit)
        return ranked or ranker.rank(item.lemmas, item.candidates, limit=limit)


def _as_ranking(results: Sequence[RankedResult]) -> Ranking:
    return [(result.event_id, result.score) for result in results]


def evaluate(
    prepared: Sequence[PreparedQuery], rankings: Sequence[Ranking], threshold: float
) -> Metrics:
    """Метрики выдачи после отсечения по порогу.

    Recall@k — «capped recall»: доля из min(k, число подходящих) мест, занятых
    подходящими записями (у многих запросов подходящих записей десятки).
    Цель подбора — среднее по всем запросам: обратный ранг первого подходящего
    результата для запросов с ответом и 1/0 за пустую выдачу для запросов без ответа.
    """
    recalls_1, recalls_5, reciprocal_ranks, no_answer_hits = [], [], [], []
    empty_on_answerable = 0
    for item, ranking in zip(prepared, rankings, strict=True):
        returned = [event_id for event_id, score in ranking if score >= threshold]
        relevant = item.query.relevant_ids
        if not item.query.expects_answer:
            no_answer_hits.append(float(not returned))
            continue
        empty_on_answerable += not returned
        recalls_1.append(_capped_recall(returned, relevant, depth=1))
        recalls_5.append(_capped_recall(returned, relevant, depth=RECALL_DEPTH))
        reciprocal_ranks.append(_reciprocal_rank(returned, relevant))
    return Metrics(
        recall_at_1=statistics.fmean(recalls_1),
        recall_at_5=statistics.fmean(recalls_5),
        mrr=statistics.fmean(reciprocal_ranks),
        no_answer_accuracy=statistics.fmean(no_answer_hits) if no_answer_hits else math.nan,
        empty_on_answerable=empty_on_answerable,
        objective=statistics.fmean([*reciprocal_ranks, *no_answer_hits]),
    )


def _capped_recall(returned: Sequence[int], relevant: frozenset[int], *, depth: int) -> float:
    found = sum(event_id in relevant for event_id in returned[:depth])
    return found / min(depth, len(relevant))


def _reciprocal_rank(returned: Sequence[int], relevant: frozenset[int]) -> float:
    for position, event_id in enumerate(returned, start=1):
        if event_id in relevant:
            return 1.0 / position
    return 0.0


def group_by_title(
    prepared: Sequence[PreparedQuery], rankings: Sequence[Ranking], corpus: Corpus
) -> tuple[list[PreparedQuery], list[Ranking]]:
    """Выдача, сгруппированная по названию, как её покажет бэкенд: одна строка на название.

    Каждая запись заменяется первой записью с тем же текстом; подходящие записи — тоже,
    поэтому метрики считают уникальные названия, а не повторы.
    """
    first_with_text: dict[str, int] = {}
    canonical = {
        event_id: first_with_text.setdefault(text, event_id)
        for event_id, text in zip(corpus.event_ids, corpus.texts, strict=True)
    }
    grouped_rankings = []
    for ranking in rankings:
        groups: dict[int, float] = {}
        for event_id, score in ranking:
            groups.setdefault(canonical[event_id], score)
        grouped_rankings.append(list(groups.items())[:RESULT_LIMIT])
    grouped_prepared = [
        replace(
            item,
            query=replace(
                item.query,
                relevant_ids=frozenset(canonical[i] for i in item.query.relevant_ids),
            ),
        )
        for item in prepared
    ]
    return grouped_prepared, grouped_rankings


@dataclass(frozen=True, slots=True)
class TuningChoice:
    params: RankingParams
    objective: float
    plateau: tuple[float, float]


def tune(prepared: Sequence[PreparedQuery], scored: ScoredGrid) -> TuningChoice:
    """Лучшие веса по цели; порог — середина плато, где цель почти максимальна.

    Середина плато, а не точка максимума, оставляет запас с обеих сторон: и от
    запросов без ответа, которые порог должен отсечь, и от слабых верных ответов.
    При равной цели выигрывает более широкое плато — оно устойчивее к новым запросам.
    """
    best: TuningChoice | None = None
    for params, rankings in scored.items():
        objectives = [evaluate(prepared, rankings, t).objective for t in THRESHOLD_GRID]
        low, high = _plateau(objectives)
        candidate = TuningChoice(
            params=replace(params, threshold=round((low + high) / 2, 3)),
            objective=max(objectives),
            plateau=(low, high),
        )
        if best is None or _better(candidate, best):
            best = candidate
    if best is None:
        raise ValueError("Пустая сетка параметров")
    return best


def _plateau(objectives: Sequence[float]) -> tuple[float, float]:
    peak = max(objectives)
    peak_index = objectives.index(peak)
    low = high = peak_index
    while low > 0 and objectives[low - 1] >= peak - PLATEAU_TOLERANCE:
        low -= 1
    while high < len(objectives) - 1 and objectives[high + 1] >= peak - PLATEAU_TOLERANCE:
        high += 1
    return THRESHOLD_GRID[low], THRESHOLD_GRID[high]


def _better(candidate: TuningChoice, current: TuningChoice) -> bool:
    if not math.isclose(candidate.objective, current.objective):
        return candidate.objective > current.objective
    return _width(candidate.plateau) > _width(current.plateau)


def _width(plateau: tuple[float, float]) -> float:
    return plateau[1] - plateau[0]


def _tune_and_report(context: RankingContext) -> RankingParams:
    prepared = context.prepared
    scored = {
        params: context.rank_untuned(params)
        for params in (
            RankingParams(lexical, name, head, UNTUNED)
            for lexical in LEXICAL_WEIGHT_GRID
            for name in NAME_WEIGHT_GRID
            for head in HEAD_WEIGHT_GRID
        )
    }
    cosine_params = RankingParams(0.0, 0.0, 0.0, UNTUNED, type_weight=0.0)
    cosine_only = tune(prepared, {cosine_params: scored[cosine_params]})
    _print_metrics(
        f"Только косинус, {_describe(cosine_only.params)}",
        evaluate(prepared, scored[cosine_params], cosine_only.params.threshold),
    )
    choice = tune(prepared, scored)
    low, high = choice.plateau
    print(
        f"Подбор: {_describe(choice.params)}; цель {choice.objective:.3f}; "
        f"плато порога {low:.2f}..{high:.2f}"
    )
    _print_cross_validation(prepared, scored)
    return choice.params


def _print_cross_validation(prepared: Sequence[PreparedQuery], scored: ScoredGrid) -> None:
    """Подбор на 3/4 запросов, проверка на оставшейся четверти — оценка переобучения."""
    held_out_metrics = []
    for fold in range(CROSS_VALIDATION_FOLDS):
        train = [i for i in range(len(prepared)) if i % CROSS_VALIDATION_FOLDS != fold]
        test = [i for i in range(len(prepared)) if i % CROSS_VALIDATION_FOLDS == fold]
        choice = tune(_pick(prepared, train), {k: _pick(v, train) for k, v in scored.items()})
        rankings = scored[replace(choice.params, threshold=UNTUNED)]
        held_out_metrics.append(
            evaluate(_pick(prepared, test), _pick(rankings, test), choice.params.threshold)
        )
    print(
        f"Кросс-валидация ({CROSS_VALIDATION_FOLDS} фолда): "
        f"Recall@1 {statistics.fmean(m.recall_at_1 for m in held_out_metrics):.3f}, "
        f"MRR {statistics.fmean(m.mrr for m in held_out_metrics):.3f}, "
        f"«нет результата» {statistics.fmean(m.no_answer_accuracy for m in held_out_metrics):.3f}"
    )


def _report(
    context: RankingContext, params: RankingParams, corpus: Corpus, args: argparse.Namespace
) -> None:
    prepared, threshold = context.prepared, params.threshold
    rankings = context.rank(params, limit=RESULT_LIMIT)
    _print_metrics(f"Итог при {_describe(params)}", evaluate(prepared, rankings, threshold))
    wide = context.rank(params, limit=GROUPING_LIMIT)
    grouped_prepared, grouped_rankings = group_by_title(prepared, wide, corpus)
    _print_metrics(
        f"  По уникальным названиям (top-{GROUPING_LIMIT} записей, сгруппированных по названию)",
        evaluate(grouped_prepared, grouped_rankings, threshold),
    )
    _print_categories(prepared, rankings, threshold)
    _print_margin(prepared, context.rank_untuned(params), threshold)
    if args.show_failures:
        _print_failures(prepared, rankings, corpus)


def _tune_type_and_report(context: RankingContext, base: RankingParams) -> RankingParams:
    """Вес бонуса за тип при остальных весах и пороге из `base`.

    Порог от типа не зависит (он сравнивается с оценкой без бонуса), поэтому перебирается
    только вес. При равной цели выигрывает меньший вес — он меньше вредит, если LLM
    ошибётся с типом.
    """
    prepared = context.prepared
    best: tuple[float, RankingParams] | None = None
    for weight in TYPE_WEIGHT_GRID:
        params = replace(base, type_weight=weight)
        metrics = evaluate(prepared, context.rank(params, limit=RESULT_LIMIT), UNTUNED)
        print(
            f"  type_weight={weight}: Recall@1 {metrics.recall_at_1:.3f}, "
            f"Recall@5 {metrics.recall_at_5:.3f}, MRR {metrics.mrr:.3f}, "
            f"«нет результата» {metrics.no_answer_accuracy:.3f}, цель {metrics.objective:.3f}"
        )
        if best is None or metrics.objective > best[0] + PLATEAU_TOLERANCE:
            best = (metrics.objective, params)
    if best is None:
        raise ValueError("Пустая сетка весов типа")
    print(f"Подбор типа: {_describe(best[1])}")
    return best[1]


def _pick[T](items: Sequence[T], indexes: Sequence[int]) -> list[T]:
    return [items[i] for i in indexes]


def _describe(params: RankingParams) -> str:
    return (
        f"lexical_weight={params.lexical_weight}, name_weight={params.name_weight}, "
        f"head_weight={params.head_weight}, type_weight={params.type_weight}, "
        f"threshold={params.threshold}"
    )


def _print_metrics(title: str, metrics: Metrics) -> None:
    print(
        f"{title}\n"
        f"  Recall@1 {metrics.recall_at_1:.3f} | Recall@5 {metrics.recall_at_5:.3f} | "
        f"MRR {metrics.mrr:.3f} | «нет результата» {metrics.no_answer_accuracy:.3f} | "
        f"пустых ответов на запросы с ответом: {metrics.empty_on_answerable}"
    )


def _print_categories(
    prepared: Sequence[PreparedQuery], rankings: Sequence[Ranking], threshold: float
) -> None:
    by_category: defaultdict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(prepared):
        by_category[item.query.category].append(index)
    print("  По категориям (Recall@1 / «нет результата»):")
    for category, indexes in by_category.items():
        subset = _pick(prepared, indexes)
        if subset[0].query.expects_answer:
            value = evaluate(subset, _pick(rankings, indexes), threshold).recall_at_1
        else:
            value = _no_answer_accuracy(_pick(rankings, indexes), threshold)
        print(f"    {category:<13} {value:.3f} ({len(indexes)} запр.)")


def _no_answer_accuracy(rankings: Sequence[Ranking], threshold: float) -> float:
    return statistics.fmean(
        float(all(score < threshold for _, score in ranking)) for ranking in rankings
    )


def _print_margin(
    prepared: Sequence[PreparedQuery], rankings: Sequence[Ranking], threshold: float
) -> None:
    """Насколько порог далёк от худшего верного ответа и от лучшего «ложного» ответа."""
    correct_top = [
        ranking[0][1]
        for item, ranking in zip(prepared, rankings, strict=True)
        if item.query.expects_answer and ranking and ranking[0][0] in item.query.relevant_ids
    ]
    unanswerable_top = [
        ranking[0][1]
        for item, ranking in zip(prepared, rankings, strict=True)
        if not item.query.expects_answer and ranking
    ]
    print(
        f"  Порог {threshold}: худший верный top-1 {min(correct_top, default=math.nan):.3f}, "
        f"лучший top-1 у запросов без ответа {max(unanswerable_top, default=math.nan):.3f}"
    )


def _print_timings(timings: Timings) -> None:
    latencies = timings.query_latencies_ms
    print(
        f"  Загрузка модели {timings.model_load_s:.1f} с | "
        f"эмбеддинг 1000 записей {timings.corpus_embedding_s:.1f} с | "
        f"embed_query p50 {_percentile(latencies, 50):.0f} мс, "
        f"p95 {_percentile(latencies, 95):.0f} мс | "
        f"пиковый прирост RSS: после загрузки {timings.peak_rss_after_load_mib:.0f} МиБ, "
        f"после эмбеддинга записей {timings.peak_rss_after_corpus_mib:.0f} МиБ"
    )


def _print_failures(
    prepared: Sequence[PreparedQuery], rankings: Sequence[Ranking], corpus: Corpus
) -> None:
    text_by_id = dict(zip(corpus.event_ids, corpus.texts, strict=True))
    print("  Ошибки (top-1 не подходит или пустая выдача; повторы названий скрыты):")
    for item, ranking in zip(prepared, rankings, strict=True):
        relevant_ids = item.query.relevant_ids
        top_ok = bool(ranking) and ranking[0][0] in relevant_ids
        if top_ok or (not item.query.expects_answer and not ranking):
            continue
        first_relevant = _reciprocal_rank([event_id for event_id, _ in ranking], relevant_ids)
        position = f"{round(1 / first_relevant)}-е место" if first_relevant else "нет в выдаче"
        print(f"    «{item.query.text}» леммы={item.lemmas}; первый подходящий: {position}")
        shown_texts: set[str] = set()
        for event_id, score in ranking:
            text = text_by_id[event_id]
            if text in shown_texts:
                continue
            shown_texts.add(text)
            mark = "+" if event_id in relevant_ids else "-"
            print(f"      {mark} {score:.3f} {text}")
            if len(shown_texts) == FAILURE_TEXTS_SHOWN:
                break


def _percentile(values: Sequence[float], percent: int) -> float:
    return float(np.percentile(np.asarray(values), percent))


def _peak_rss_mib() -> float:
    """Пиковый RSS процесса: на macOS ru_maxrss в байтах, на Linux — в КиБ."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / BYTES_IN_MIB if sys.platform == "darwin" else peak / KIB_IN_MIB


if __name__ == "__main__":
    main()
