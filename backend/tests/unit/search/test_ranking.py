"""Гибридное ранжирование без модели: оценки собраны вручную."""

import math

import pytest

from app.search.interfaces import RankedResult, SearchCandidate
from app.search.ranking import HybridRanker, LemmaStatistics, RankingParams

NO_THRESHOLD = -math.inf


class NamesFromSet:
    """Детектор имён для тестов: имена — то, что передали."""

    def __init__(self, *names: str) -> None:
        self._names = frozenset(names)

    def is_proper_noun(self, lemma: str) -> bool:
        return lemma in self._names


def candidate(event_id: int, similarity: float, *lemmas: str) -> SearchCandidate:
    return SearchCandidate(event_id=event_id, lemmas=lemmas, similarity=similarity)


def make_ranker(
    *,
    documents: list[list[str]] | None = None,
    names: NamesFromSet | None = None,
    lexical_weight: float = 0.0,
    name_weight: float = 0.0,
    head_weight: float = 0.0,
    threshold: float = NO_THRESHOLD,
) -> HybridRanker:
    return HybridRanker(
        LemmaStatistics.from_documents(documents or []),
        names or NamesFromSet(),
        RankingParams(lexical_weight, name_weight, head_weight, threshold),
    )


def ids(results: list[RankedResult]) -> list[int]:
    return [result.event_id for result in results]


def test_statistics_count_documents_not_occurrences() -> None:
    statistics = LemmaStatistics.from_documents([["отчет", "отчет"], ["отчет"], ["акт"]])

    assert statistics.document_count == 3
    assert statistics.document_frequency == {"отчет": 2, "акт": 1}


def test_no_candidates_or_zero_limit_give_empty_result() -> None:
    ranker = make_ranker()

    assert ranker.rank(["договор"], [], limit=5) == []
    assert ranker.rank(["договор"], [candidate(1, 0.9, "договор")], limit=0) == []


def test_results_are_sorted_by_score_and_cut_to_limit() -> None:
    ranker = make_ranker()
    candidates = [candidate(1, 0.2), candidate(2, 0.9), candidate(3, 0.5)]

    assert ids(ranker.rank([], candidates, limit=2)) == [2, 3]


def test_cosine_only_score_equals_similarity() -> None:
    ranker = make_ranker()

    [result] = ranker.rank([], [candidate(7, 0.42)], limit=1)

    assert result.event_id == 7
    assert result.score == pytest.approx(0.42)


def test_threshold_turns_weak_matches_into_empty_answer() -> None:
    ranker = make_ranker(threshold=0.5)

    assert ranker.rank(["отпуск"], [candidate(1, 0.49), candidate(2, 0.3)], limit=5) == []


def test_score_on_threshold_is_kept() -> None:
    ranker = make_ranker(threshold=0.5)

    assert ids(ranker.rank([], [candidate(1, 0.5)], limit=5)) == [1]


def test_score_combines_similarity_and_coverage() -> None:
    ranker = make_ranker(documents=[["договор"], ["акт"]], lexical_weight=0.25)

    [result] = ranker.rank(["договор"], [candidate(1, 0.6, "подготовить", "договор")], limit=1)

    assert result.score == pytest.approx(0.75 * 0.6 + 0.25 * 1.0)


def test_matching_lemma_lifts_record_above_equal_similarity() -> None:
    ranker = make_ranker(documents=[["договор"], ["смета"]], lexical_weight=0.3)
    candidates = [candidate(1, 0.7, "смета"), candidate(2, 0.7, "договор")]

    assert ids(ranker.rank(["договор"], candidates, limit=2)) == [2, 1]


def test_rare_lemma_outweighs_common_one() -> None:
    documents = [["проверить", "сайт"]] * 8 + [["проверить", "вектор"]]
    ranker = make_ranker(documents=documents, lexical_weight=0.5)
    candidates = [candidate(1, 0.5, "проверить", "сайт"), candidate(2, 0.5, "вектор")]

    assert ids(ranker.rank(["проверить", "вектор"], candidates, limit=2)) == [2, 1]


def test_query_lemma_absent_everywhere_does_not_dilute_coverage() -> None:
    ranker = make_ranker(documents=[["договор"]], lexical_weight=0.5)
    record = [candidate(1, 0.4, "договор")]

    [with_unknown] = ranker.rank(["договор", "отпуск"], record, limit=1)
    [without_unknown] = ranker.rank(["договор"], record, limit=1)

    assert with_unknown.score == pytest.approx(without_unknown.score)


def test_lemma_missing_from_statistics_is_counted_from_candidates() -> None:
    ranker = make_ranker(documents=[["договор"]], lexical_weight=0.5)

    [result] = ranker.rank(["билет"], [candidate(1, 0.4, "купить", "билет")], limit=1)

    assert result.score == pytest.approx(0.5 * 0.4 + 0.5 * 1.0)


def test_person_name_beats_closer_vector_with_other_name() -> None:
    ranker = make_ranker(names=NamesFromSet("иван", "сергей"), name_weight=0.15)
    candidates = [candidate(1, 0.80, "встреча", "сергей"), candidate(2, 0.70, "встреча", "иван")]

    results = ranker.rank(["встреча", "иван"], candidates, limit=2)

    assert ids(results) == [2, 1]
    assert results[0].score == pytest.approx(0.70 + 0.15)
    assert results[1].score == pytest.approx(0.80 - 0.15)


def test_unknown_person_cuts_records_without_that_name() -> None:
    ranker = make_ranker(names=NamesFromSet("петр", "иван"), name_weight=0.2, threshold=0.5)

    assert ranker.rank(["встреча", "петр"], [candidate(1, 0.65, "встреча", "иван")], limit=5) == []


def test_name_term_is_neutral_without_names_in_query() -> None:
    ranker = make_ranker(names=NamesFromSet("иван"), name_weight=0.2)

    [result] = ranker.rank(["договор"], [candidate(1, 0.6, "договор", "иван")], limit=1)

    assert result.score == pytest.approx(0.6)


def test_query_naming_record_head_ranks_it_first() -> None:
    ranker = make_ranker(head_weight=0.05)
    candidates = [
        candidate(1, 0.80, "отправить", "итог", "встреча", "иван"),
        candidate(2, 0.78, "встреча", "иван", "crm"),
    ]

    assert ids(ranker.rank(["встреча", "иван"], candidates, limit=2)) == [2, 1]


def test_record_without_lemmas_gets_no_head_bonus() -> None:
    ranker = make_ranker(head_weight=0.05)

    [result] = ranker.rank(["встреча"], [candidate(1, 0.5)], limit=1)

    assert result.score == pytest.approx(0.5)


def test_equal_scores_put_newer_record_first() -> None:
    ranker = make_ranker()
    duplicates = [candidate(3, 0.7, "договор"), candidate(9, 0.7, "договор"), candidate(5, 0.7)]

    assert ids(ranker.rank([], duplicates, limit=3)) == [9, 5, 3]


def test_duplicate_candidate_is_returned_once_with_best_score() -> None:
    ranker = make_ranker()

    [result] = ranker.rank([], [candidate(1, 0.3), candidate(1, 0.6)], limit=5)

    assert result.event_id == 1
    assert result.score == pytest.approx(0.6)


def test_default_params_are_the_tuned_ones() -> None:
    assert RankingParams() == RankingParams(
        lexical_weight=0.1, name_weight=0.2, head_weight=0.05, threshold=0.52
    )
