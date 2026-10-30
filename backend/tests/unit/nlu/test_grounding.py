"""Сверка ссылки на запись со словами реплики."""

import pytest

from app.nlu.grounding import (
    names_event_type,
    names_moment,
    names_record_by_pronoun,
    same_record,
    user_description,
)


@pytest.mark.parametrize(
    ("model_query", "text", "expected"),
    [
        ("встреча с Иваном", "Перенеси встречу с Иваном на пятницу", "встреча с Иваном"),
        ("позвонить Ивану", "Я уже позвонил Ивану", "позвонить Ивану"),
        ("отчёт", "Отметь задачу про отчёт как выполненную", "отчёт"),
        ("созвон", "Перенеси завтрашний созвон на 16:00", "созвон"),
        ("купить билеты", "Переименуй задачу купить билеты в Казань", "купить билеты"),
    ],
)
def test_description_from_user_words_is_kept(model_query: str, text: str, expected: str) -> None:
    assert user_description(model_query, text) == expected


def test_title_from_focus_is_replaced_by_user_words() -> None:
    text = "Отметь звонок Ивану как сделанный"

    assert user_description("Встреча с Иваном", text) == "звонок Ивану"


def test_prepositions_between_user_words_are_kept() -> None:
    text = "перенеси звонок Ивану по договору на пятницу"

    assert user_description("Встреча с Иваном по CRM", text) == "звонок Ивану по договору"


def test_day_words_are_not_part_of_description() -> None:
    text = "Отмени в четверг созвон с Орбитой"

    assert user_description("Подготовиться к встрече с Вектором", text) == "созвон с Орбитой"


@pytest.mark.parametrize("text", ["Удали её", "А перенеси её на завтра", "Отметь как выполненное"])
def test_pronoun_only_reply_has_no_description(text: str) -> None:
    assert user_description("Созвон с партнёром", text) is None


def test_missing_model_description_is_recovered_from_user_words() -> None:
    assert user_description(None, "Отметь звонок Ивану") == "звонок Ивану"


@pytest.mark.parametrize(
    "text",
    [
        "Перенеси на следующую неделю",
        "Перенеси через два дня",
        "Перенеси через день",
        "Перенеси на следующий четверг",
        "Перенеси на этой неделе",
        "Перенеси на 06:30",
    ],
)
def test_time_only_command_does_not_invent_description(text: str) -> None:
    assert user_description(None, text) is None


def test_description_of_only_stop_words_is_kept() -> None:
    assert user_description("задача", "Удали задачу") == "задача"


@pytest.mark.parametrize(
    "text",
    [
        "Перенеси завтрашний созвон",
        "Удали встречу в четверг",
        "Отметь задачу на 26 ноября",
        "Отмени созвон в 15:00",
        "Удали утреннюю планёрку",
        "Отметь звонок на этой неделе",
    ],
)
def test_moment_words(text: str) -> None:
    assert names_moment(text)


@pytest.mark.parametrize(
    "text", ["Отметь звонок Ивану как сделанный", "Удали её", "Отметь среди задач отчёт"]
)
def test_no_moment_words(text: str) -> None:
    assert not names_moment(text)


@pytest.mark.parametrize(
    "text",
    [
        "Удали встречу с Иваном",
        "Отмени созвон",
        "Отметь задачу",
        "Удали напоминание",
        "Удали планёрку",
    ],
)
def test_event_type_words(text: str) -> None:
    assert names_event_type(text)


@pytest.mark.parametrize("text", ["Отметь звонок Ивану как сделанный", "Удали её"])
def test_call_is_not_an_event_type(text: str) -> None:
    """«Позвонить Ивану» — задача или напоминание, «Созвон с Иваном» — встреча."""
    assert not names_event_type(text)


def test_same_record_ignores_word_forms() -> None:
    assert same_record("встречу с Иваном", "Встреча с Иваном")
    assert not same_record("звонок Ивану", "Встреча с Иваном")


@pytest.mark.parametrize(
    "text",
    [
        "А перенеси её на завтра",
        "нет, лучше перенеси её на понедельник на 10 утра",
        "не удаляй, сдвинь её на 17:00",
        "Удали эту встречу",
        "Отметь эту задачу выполненной",
        "Перенеси эту встречу на следующую неделю",
        "Перенеси эту встречу через два дня",
        "Перенеси эту встречу на завтра в десять тридцать",
        "Перенеси эту встречу на завтра на полчаса",
        "Перенеси эту встречу на завтра на час",
        "Отметь эту встречу в 15:00 выполненной",
        "Отметь это выполненным",
        "Отметь его выполненным",
        "Переименуй её в созвон с партнёрами",
    ],
)
def test_record_named_by_pronoun(text: str) -> None:
    assert names_record_by_pronoun(text)


@pytest.mark.parametrize(
    "text",
    [
        "Отметь звонок Ивану как сделанный",
        "Удали встречу с Иваном и его командой",
        "Перенеси встречу с Ольгой и её помощником на пятницу",
        "Удали задачу проверить этот отчёт",
        "Удали задачу про этот отчёт",
        "Перенеси на этот четверг созвон с Иваном",
        "Отметь задачу позвонить ей",
        "Отметь эту задачу Купить хлеб выполненной",
        "Удали эту встречу с Иваном",
        "Перенеси эту встречу с Иваном на завтра",
        "Отметь этот звонок Ивану выполненным",
    ],
)
def test_no_record_pronoun(text: str) -> None:
    """«Его командой», «её помощником» — притяжательные, а не ссылка на запись."""
    assert not names_record_by_pronoun(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Переименуй эту встречу в Созвон с партнёрами", True),
        ("Переименуй эту встречу в Созвон с партнерами", True),
        ("Назови эту задачу Купить хлеб", True),
        ("Переименуй эту встречу с Иваном в Созвон с партнёрами", False),
    ],
)
def test_new_title_does_not_describe_the_referenced_record(text: str, expected: bool) -> None:
    new_title = "Купить хлеб" if text.startswith("Назови") else "Созвон с партнёрами"
    assert names_record_by_pronoun(text, new_title=new_title) is expected


@pytest.mark.parametrize("text", ["нет, лучше перенеси на понедельник", "тогда сдвинь на 17:00"])
def test_conversation_fillers_are_not_description(text: str) -> None:
    assert user_description("Созвон с Орбитой по презентации", text) is None
