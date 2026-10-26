"""Гибридное ранжирование: близость по смыслу + совпадение лемм + имена людей + тип.

Эмбеддинги хорошо ловят синонимы («созвон» ↔ «звонок», «ТЗ» ↔ «техническое
задание»), но считают имена взаимозаменяемыми: «встреча с Иваном» для них почти
то же, что «встреча с Сергеем». Леммы точны на совпадающих словах, но слепы к
синонимам. Итоговая оценка складывает оба сигнала, поправку за имя человека
бонус, если запрос называет главное слово записи («встреча» в «Встреча с Иваном…»),
и мягкий бонус за тип записи, который назвал разбор запроса («встреча с Иваном» → встречи).
"""

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.enums import EventType
from app.search.interfaces import RankedResult, SearchCandidate


@dataclass(frozen=True, slots=True)
class LemmaStatistics:
    """Частоты лемм по корпусу записей — для веса редких слов (idf).

    Можно передать частоты только для лемм запроса: ранжированию другие не нужны.
    Лемма, которой нет в статистике, но которая есть у кандидатов, считается
    по кандидатам — так новые записи пользователя не выпадают из лексического сигнала.
    """

    document_count: int
    document_frequency: Mapping[str, int]

    @classmethod
    def from_documents(cls, documents: Iterable[Sequence[str]]) -> "LemmaStatistics":
        """Статистика по спискам лемм записей (одна запись — один список)."""
        frequency: Counter[str] = Counter()
        document_count = 0
        for lemmas in documents:
            frequency.update(set(lemmas))
            document_count += 1
        return cls(document_count=document_count, document_frequency=dict(frequency))


@dataclass(frozen=True, slots=True)
class RankingParams:
    """Веса гибридной оценки и порог отсечения.

    `score = (1 - lexical_weight) * similarity + lexical_weight * coverage
    ± name_weight + head_weight + type_weight`, где:

    - `coverage` — доля idf-веса лемм запроса, найденных в записи (0..1);
    - `name_weight` прибавляется, если имя человека из запроса есть в записи, и вычитается,
      если нет: эмбеддинги путают имена, а для пользователя это разные встречи;
    - `head_weight` прибавляется, если запрос называет главное (первое) слово записи:
      на «встреча с Иваном» «Встреча с Иваном по CRM» выше, чем «Отправить итоги встречи
      Иваном». Леммы идут в порядке появления, первая — то, чем запись является;
    - `type_weight` прибавляется записям типа `preferred_type` из разбора запроса. Это бонус,
      а не фильтр: если LLM ошиблась с типом, нужная запись опустится, но не пропадёт.
      Порог `threshold` сравнивается с оценкой без этого бонуса.

    Значения по умолчанию подобраны на `tests/fixtures/search_eval.json` для
    `deepvk/USER-bge-m3` (см. `docs/search.md`); для другой модели их нужно подобрать заново.
    `type_weight` — наименьший вес с лучшим результатом на запросах с типом из разбора
    (`eval_search --type-bonus --tune-type`).
    """

    lexical_weight: float = 0.1
    name_weight: float = 0.2
    head_weight: float = 0.05
    threshold: float = 0.52
    type_weight: float = 0.075


DEFAULT_RANKING_PARAMS = RankingParams()


class ProperNounDetector(Protocol):
    """Отличает имена людей среди лемм: «иван» — имя, «вектор» — нет."""

    def is_proper_noun(self, lemma: str) -> bool:
        """Является ли лемма именем, фамилией или отчеством."""
        ...


@dataclass(frozen=True, slots=True)
class _QueryProfile:
    lemmas: frozenset[str]
    lemma_weights: Mapping[str, float]
    total_weight: float
    person_names: frozenset[str]


class HybridRanker:
    """Ранжирование по протоколу `Ranker` из `app.search.interfaces`."""

    def __init__(
        self,
        statistics: LemmaStatistics,
        names: ProperNounDetector,
        params: RankingParams = DEFAULT_RANKING_PARAMS,
    ) -> None:
        self._statistics = statistics
        self._names = names
        self._params = params

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        """Лучшие записи по убыванию `score`; пустой список — «ничего похожего нет».

        Порог применяется к оценке без бонуса за тип: тип из разбора запроса меняет только
        порядок, но не делает похожей запись, которая на запрос не похожа. Иначе на «встречу
        с Петром», которой нет, нашлась бы любая встреча. Записи типа `preferred_type`
        получают бонус `type_weight` к `score`, остальные не отсекаются.
        При равной оценке выше запись с большим `event_id` (созданная позже).
        """
        if limit <= 0 or not candidates:
            return []
        query = self._profile_query(query_lemmas, candidates)
        best_by_event: dict[int, SearchCandidate] = {}
        base_scores: dict[int, float] = {}
        for candidate in candidates:
            score = self._score(query, candidate)
            if score >= base_scores.get(candidate.event_id, -math.inf):
                base_scores[candidate.event_id] = score
                best_by_event[candidate.event_id] = candidate
        relevant = [
            RankedResult(
                event_id=event_id,
                score=score + self._type_bonus(best_by_event[event_id], preferred_type),
            )
            for event_id, score in base_scores.items()
            if score >= self._params.threshold
        ]
        relevant.sort(key=lambda result: (result.score, result.event_id), reverse=True)
        return relevant[:limit]

    def _profile_query(
        self, query_lemmas: Sequence[str], candidates: Sequence[SearchCandidate]
    ) -> _QueryProfile:
        unique_lemmas = list(dict.fromkeys(query_lemmas))
        frequency = self._document_frequency(unique_lemmas, candidates)
        document_count = max(self._statistics.document_count, len(candidates))
        weights = {
            lemma: _inverse_document_frequency(frequency[lemma], document_count)
            for lemma in unique_lemmas
            if frequency[lemma] > 0
        }
        return _QueryProfile(
            lemmas=frozenset(unique_lemmas),
            lemma_weights=weights,
            total_weight=sum(weights.values()),
            person_names=frozenset(filter(self._names.is_proper_noun, unique_lemmas)),
        )

    def _document_frequency(
        self, lemmas: Sequence[str], candidates: Sequence[SearchCandidate]
    ) -> dict[str, int]:
        known = self._statistics.document_frequency
        frequency = {lemma: known.get(lemma, 0) for lemma in lemmas}
        unknown = {lemma for lemma, count in frequency.items() if count == 0}
        if unknown:
            for candidate in candidates:
                for lemma in unknown.intersection(candidate.lemmas):
                    frequency[lemma] += 1
        return frequency

    def _score(self, query: _QueryProfile, candidate: SearchCandidate) -> float:
        record_lemmas = set(candidate.lemmas)
        lexical_weight = self._params.lexical_weight
        semantic = (1.0 - lexical_weight) * candidate.similarity
        lexical = lexical_weight * _coverage(query, record_lemmas)
        head = self._params.head_weight if _names_head(query, candidate.lemmas) else 0.0
        return semantic + lexical + head + self._name_adjustment(query, record_lemmas)

    def _type_bonus(self, candidate: SearchCandidate, preferred_type: EventType | None) -> float:
        if preferred_type is None or candidate.event_type != preferred_type:
            return 0.0
        return self._params.type_weight

    def _name_adjustment(self, query: _QueryProfile, record_lemmas: set[str]) -> float:
        if not query.person_names:
            return 0.0
        if query.person_names.isdisjoint(record_lemmas):
            return -self._params.name_weight
        return self._params.name_weight


def _inverse_document_frequency(document_frequency: int, document_count: int) -> float:
    """Сглаженный idf: редкое слово весит больше частого, вес всегда больше нуля."""
    return math.log((document_count + 1) / (document_frequency + 1)) + 1.0


def _names_head(query: _QueryProfile, record_lemmas: Sequence[str]) -> bool:
    return bool(record_lemmas) and record_lemmas[0] in query.lemmas


def _coverage(query: _QueryProfile, record_lemmas: set[str]) -> float:
    """Доля idf-веса лемм запроса, которые есть в записи; 0, если сравнивать не с чем.

    Леммы запроса, которых нет ни в одной записи («отпуск», опечатка «презинтация»),
    не учитываются: совпасть по ним нельзя, их смысл оценивает эмбеддинг.
    """
    if query.total_weight == 0.0:
        return 0.0
    matched = sum(weight for lemma, weight in query.lemma_weights.items() if lemma in record_lemmas)
    return matched / query.total_weight
