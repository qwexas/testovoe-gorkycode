"""Создание или перенос по глаголам реплики и названия-заглушки."""

import pytest

from app.nlu.command_words import (
    asks_to_change,
    asks_to_create,
    creation_over_change,
    is_generic_title,
    other_commands,
)
from app.nlu.expressions import DateKind
from app.nlu.interfaces import Action
from app.nlu.schema import Extraction


@pytest.mark.parametrize(
    "text",
    [
        "Поставь встречу с Иваном на следующей неделе",
        "Добавь созвон с партнёром",
        "Создай задачу",
        "Запланируй встречу с командой",
        "Назначь встречу с Ольгой на пятницу",
        "Напомни позвонить маме",
        "Запиши встречу с юристом",
        "На следующей неделе нужно встретиться с Иваном",
        "надо купить билеты",
    ],
)
def test_create_words(text: str) -> None:
    assert asks_to_create(text)


@pytest.mark.parametrize(
    "text",
    [
        "Перенеси встречу с Иваном на следующую неделю",
        "Сдвинь созвон на 17:00",
        "Передвинь планёрку на утро",
        "Перемести встречу на пятницу",
        "Измени время встречи",
        "Отложи задачу на завтра",
        "Поменяй время созвона",
    ],
)
def test_change_words(text: str) -> None:
    assert asks_to_change(text)


def test_question_has_neither() -> None:
    assert not asks_to_create("Что у меня завтра?")
    assert not asks_to_change("Что у меня завтра?")


def reschedule(**fields: object) -> Extraction:
    return Extraction.model_validate({"action": "reschedule", **fields})


def test_reschedule_with_create_verb_becomes_create() -> None:
    extraction = reschedule(
        event_type="meeting", query="встреча с Иваном", target_date="mon", date="next_week"
    )

    created = creation_over_change(extraction, "Поставь встречу с Иваном на следующей неделе")

    assert created.action is Action.CREATE
    assert created.title == "встреча с Иваном"
    assert created.query == ""
    assert created.target_date is DateKind.NONE
    assert created.date is DateKind.NEXT_WEEK


def test_title_from_model_wins_over_description() -> None:
    extraction = reschedule(query="встреча с Иваном", title="Встреча с Иваном по CRM")

    created = creation_over_change(extraction, "Добавь встречу с Иваном по CRM на пятницу")

    assert created.title == "Встреча с Иваном по CRM"


def test_change_verb_keeps_reschedule() -> None:
    extraction = reschedule(query="встреча с Иваном", date="next_week")

    kept = creation_over_change(extraction, "Перенеси встречу с Иваном на следующую неделю")

    assert kept is extraction


def test_both_verbs_keep_reschedule() -> None:
    extraction = reschedule(query="встреча с Иваном", date="fri")

    kept = creation_over_change(extraction, "Надо перенести встречу с Иваном на пятницу")

    assert kept is extraction


@pytest.mark.parametrize("text", ["Поставь её на пятницу", "Поставь эту встречу на пятницу"])
def test_pronoun_keeps_reschedule(text: str) -> None:
    extraction = reschedule(date="fri")

    assert creation_over_change(extraction, text) is extraction


def test_about_last_keeps_reschedule() -> None:
    extraction = reschedule(about_last=True, date="fri")

    assert creation_over_change(extraction, "Поставь на пятницу") is extraction


def test_other_actions_are_not_touched() -> None:
    extraction = Extraction.model_validate({"action": "delete", "query": "встреча"})

    assert creation_over_change(extraction, "Добавь и удали встречу") is extraction


@pytest.mark.parametrize(
    "title", ["Встреча", "встреча", "Задача", "Напоминание", "Дело", "Новая встреча", "Событие"]
)
def test_generic_titles(title: str) -> None:
    assert is_generic_title(title)


@pytest.mark.parametrize(
    "title",
    ["Встреча с Иваном", "Созвон", "Планёрка", "Совещание", "Встреча CRM", "Купить молоко", ""],
)
def test_real_titles(title: str) -> None:
    """«Созвон», «Планёрка» — уже содержание: формат встречи, а не просто тип."""
    assert not is_generic_title(title)


@pytest.mark.parametrize(
    ("text", "rest"),
    [
        ("Перенеси планёрку на 11 и удали встречу с Петром", "удали встречу с Петром"),
        ("Отмени встречу и поставь новую на пятницу", "поставь новую на пятницу"),
        ("Перенеси созвон на 17, а потом удали задачу", "удали задачу"),
        ("Удали встречу с Петром, а созвон перенеси на завтра", "созвон перенеси на завтра"),
        ("Создай задачу купить хлеб и создай задачу купить молоко", "создай задачу купить молоко"),
    ],
)
def test_other_commands_are_split_off(text: str, rest: str) -> None:
    assert other_commands(text) == rest


@pytest.mark.parametrize(
    "text",
    [
        "Перенеси встречу с Иваном на 17:00 на полчаса",
        "Поставь задачу добавить отчёт",
        "Напомни купить хлеб и молоко",
        "нет, отмени, перенеси её на пятницу",
        "не удаляй, сдвинь её на 17:00",
        "Создай встречу с Иваном и задачу купить билеты",
    ],
)
def test_single_command(text: str) -> None:
    """Инфинитив — содержание записи; «создай A и B» без второго глагола ловит модель (`rest`)."""
    assert other_commands(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Поставь задачу: найди подрядчика",
        "Создай задачу «удали старые файлы»",
        'Создай задачу "удали старые файлы"',
        "Напомни сказать Ивану: перенеси релиз",
    ],
)
def test_command_in_title_is_content(text: str) -> None:
    """Глагол в кавычках или после двоеточия — название записи, а не вторая команда."""
    assert other_commands(text) is None


def test_command_in_model_title_is_content() -> None:
    assert other_commands("Создай напоминание удали кэш в пятницу", "Удалить кэш") is None


def test_command_after_quoted_title_is_split_off() -> None:
    text = "Создай задачу «удали старые файлы» и удали встречу с Петром"

    assert other_commands(text, "Удали старые файлы") == "удали встречу с Петром"


def test_creation_over_change_forgets_record_time() -> None:
    extraction = reschedule(query="встреча с Иваном", target_time="10:00", time="12:00")

    created = creation_over_change(extraction, "Поставь встречу с Иваном на 12")

    assert created.action is Action.CREATE
    assert created.target_time == ""
