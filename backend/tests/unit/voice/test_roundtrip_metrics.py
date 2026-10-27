"""Метрики замера `scripts/voice_roundtrip.py`: сравнение текстов, WER, перцентили."""

import pytest

from scripts.voice_roundtrip import Recognition, comparable, edit_distance, percentile, score


@pytest.mark.parametrize(
    ("reference", "hypothesis"),
    [
        ("Добавь встречу с командой завтра в 15:00", "Добавь встречу с командой завтра в 15.00."),
        ("Напомни мне завтра в 10 утра", "напомни мне завтра в десять утра"),
        ("Созвон в 8:45", "Созвон в 8 часов 45 минут."),
        ("Встреча в 15:00", "Встреча в 15 часов, 0 минут"),
        ("Я когда-то ставил задачу, найди ее", "Я когда-то ставил задачу. Найди её!"),
        ("Перенеси созвон по CRM", "Перенеси созвон по CRM."),
        ("Согласовать ТЗ", "согласовать ТЗ"),
    ],
)
def test_same_phrase_written_differently_is_equal(reference: str, hypothesis: str) -> None:
    assert comparable(reference) == comparable(hypothesis)


def test_different_words_are_not_equal() -> None:
    assert comparable("Созвон с Ольгой") != comparable("Созван с Ольгой")


@pytest.mark.parametrize(
    ("reference", "hypothesis", "distance"),
    [
        ("", "", 0),
        ("абв", "абв", 0),
        ("абв", "аб", 1),
        ("абв", "абвг", 1),
        ("абв", "агв", 1),
        ("", "абв", 3),
    ],
)
def test_edit_distance(reference: str, hypothesis: str, distance: int) -> None:
    assert edit_distance(reference, hypothesis) == distance


def test_percentile_uses_nearest_rank() -> None:
    values = [float(value) for value in range(1, 21)]

    assert percentile(values, 0.5) == 10.0
    assert percentile(values, 0.95) == 19.0
    assert percentile([3.0], 0.95) == 3.0


def result(reference: str, hypothesis: str, latency: float = 1.0) -> Recognition:
    return Recognition("clip.webm", "silero-xenia", "webm", reference, hypothesis, 2.0, latency)


def test_score_counts_exact_matches_errors_and_false_speech() -> None:
    results = [
        result("что у меня сегодня", "Что у меня сегодня?", latency=1.0),
        result("найди задачу про отчет", "найди задачу про отчёт", latency=2.0),
        result("удали встречу", "удали встречи", latency=3.0),
        result("", "Продолжение следует..."),
        result("", ""),
    ]

    scores = score(results)

    assert scores.clips == 3
    assert scores.exact == pytest.approx(2 / 3)
    assert scores.wer == pytest.approx(1 / 10)
    assert scores.false_speech == 1
    assert scores.latency_p50 == 2.0
