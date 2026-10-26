"""Время поиска по маркерам в реплике — страховка от потерянного `time_scope`."""

import pytest

from app.nlu.interfaces import TimeScope
from app.nlu.time_scope import search_time_scope, time_scope_in_text


@pytest.mark.parametrize(
    "text",
    [
        "Когда у меня была встреча с Иваном?",
        "Я когда-то ставил задачу по договору, найди ее",
        "Когда я звонил Ивану?",
        "Что мы обсуждали с Ольгой по CRM?",
        "Были ли у меня созвоны с Пульсом?",
        "Когда я отправлял Ольге коммерческое предложение?",
        "Найди задачу, которую я раньше ставил про отчёт",
        "Покажи последнюю планёрку",
        "Что было на прошлой встрече с Вектором?",
        "Найди предыдущий созвон с Орбитой",
        "Как давно я созванивался с Севером",
    ],
)
def test_past_markers(text: str) -> None:
    assert time_scope_in_text(text) is TimeScope.PAST


@pytest.mark.parametrize(
    "text",
    [
        "Когда у меня будет созвон с Орбитой?",
        "А когда следующая встреча с Иваном?",
        "Найди ближайшую встречу с Вектором",
        "Какие предстоящие встречи с Натальей?",
        "Что у меня запланировано с Максимом?",
        "Когда я позвоню Ивану?",
        "Когда мы встретимся с дизайнером",
        "Скоро у меня созвон с Пульсом?",
        "когда будут планёрки по интеграции",
    ],
)
def test_future_markers(text: str) -> None:
    assert time_scope_in_text(text) is TimeScope.FUTURE


@pytest.mark.parametrize(
    "text",
    [
        "Найди задачу про презентацию",
        "Покажи всё про договор с Марией",
        "Созвон с Орбитой",
        "Когда у меня созвон с Орбитой?",
    ],
)
def test_no_markers(text: str) -> None:
    assert time_scope_in_text(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Найди встречу с Борисом на прошлой неделе",
        "Созвон с Пульсом в следующем месяце",
        "Найди встречу с Вектором в ближайшую пятницу",
        "Совещание по CRM на следующей неделе",
        "Что по договору в прошлом году",
    ],
)
def test_period_words_are_not_markers(text: str) -> None:
    """«На прошлой неделе» — период: его разбирает модель в `date`, а не время поиска."""
    assert time_scope_in_text(text) is None


@pytest.mark.parametrize("text", ["Найдёшь встречу с Иваном?", "Подскажешь, где отчёт?"])
def test_second_person_request_is_not_future(text: str) -> None:
    """«Найдёшь», «подскажешь» — вежливая просьба к ассистенту, а не время события."""
    assert time_scope_in_text(text) is None


def test_participle_planned_is_future_not_past() -> None:
    """Причастие «запланированные» грамматически прошедшего времени, но это не глагол."""
    assert time_scope_in_text("Покажи запланированные встречи") is TimeScope.FUTURE


def test_contradicting_markers_give_no_answer() -> None:
    assert time_scope_in_text("Когда будет встреча, которую мы перенесли?") is None


def test_markers_override_model() -> None:
    assert search_time_scope(TimeScope.ANY, "Когда у меня будет созвон?") is TimeScope.FUTURE
    assert search_time_scope(TimeScope.FUTURE, "Когда была встреча?") is TimeScope.PAST


def test_model_answer_kept_without_markers() -> None:
    assert search_time_scope(TimeScope.PAST, "Найди договор с Марией") is TimeScope.PAST


def test_model_answer_kept_when_markers_contradict() -> None:
    text = "Когда будет встреча, которую мы перенесли?"

    assert search_time_scope(TimeScope.FUTURE, text) is TimeScope.FUTURE
