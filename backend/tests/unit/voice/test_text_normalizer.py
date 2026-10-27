"""Нормализация текста для Silero: время, даты, числа, латиница, знаки — на реальных ответах."""

import re
from datetime import timedelta

import pytest

from app.core.dialog import phrases
from app.core.enums import EventStatus, EventType
from app.nlu.interfaces import Action, Period
from app.voice.text_normalizer import (
    EM_DASH,
    EN_DASH,
    MAX_CHUNK_CHARS,
    normalize_for_speech,
    speech_chunks,
)
from tests.unit.dialog.support import NOW, TODAY, TOMORROW, at, card, day_period

NO_BREAK_SPACE = chr(0xA0)
SILERO_ALPHABET = re.compile(rf"^[а-яёА-ЯЁ+,.!?:;{EN_DASH}…\s-]*$")
"""Всё, что Silero умеет прочесть: кириллица, ударение «+» и знаки препинания."""


def assert_speakable(text: str) -> None:
    assert SILERO_ALPHABET.match(text), f"Silero не прочтёт: {text!r}"


# --- Время -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("в 15:00", "в пятнадцать ноль-ноль"),
        ("в 8:45", "в восемь сорок пять"),
        ("8:45", "восемь сорок пять"),
        ("в 9:05", "в девять ноль пять"),
        ("в 09:30", "в девять тридцать"),
        ("в 21:21", "в двадцать один двадцать одна"),
        ("в 12:02", "в двенадцать ноль две"),
        ("в 1:30", "в час тридцать"),
        ("в 0:00", "в полночь"),
        ("в 0:15", "в ноль пятнадцать"),
        ("в 23:59", "в двадцать три пятьдесят девять"),
        ("с 15:00 до 16:30", "с пятнадцати ноль-ноль до шестнадцати тридцати"),
        ("к 10:00", "к десяти ноль-ноль"),
        ("после 1:00", "после часа ноль-ноль"),
        ("до 0:00", "до полуночи"),
        ("С 9:00", "С девяти ноль-ноль"),
    ],
)
def test_times(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


@pytest.mark.parametrize(
    "dash",
    [EN_DASH, EM_DASH, "-"],
)
def test_time_range_reads_as_from_to(dash: str) -> None:
    assert normalize_for_speech(f"«Планёрка» (15:00{dash}16:00)") == (
        "Планёрка, с пятнадцати ноль-ноль до шестнадцати ноль-ноль,"
    )


@pytest.mark.parametrize("text", ["25:00", "12:75", "1:2", "15:000"])
def test_not_a_time_is_read_as_numbers(text: str) -> None:
    spoken = normalize_for_speech(text)

    assert "ноль-ноль" not in spoken
    assert_speakable(spoken)


# --- Даты ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("27 октября", "двадцать седьмого октября"),
        ("1 января", "первого января"),
        ("31 декабря", "тридцать первого декабря"),
        ("5 марта 2026", "пятого марта две тысячи двадцать шестого года"),
        ("5 марта 2026 года", "пятого марта две тысячи двадцать шестого года"),
        ("5 марта 2026 г.", "пятого марта две тысячи двадцать шестого года"),
        ("на 12 ноября", "на двенадцатое ноября"),
        ("по 12 ноября", "по двенадцатое ноября"),
        ("к 12 ноября", "к двенадцатому ноября"),
        ("с 9 ноября", "с девятого ноября"),
        ("до 3 мая", "до третьего мая"),
        ("27.10", "двадцать седьмого октября"),
        ("05.03.26", "пятого марта две тысячи двадцать шестого года"),
        ("05.03.2027", "пятого марта две тысячи двадцать седьмого года"),
        ("в 2026 году", "в две тысячи двадцать шестом году"),
        ("2027 год", "две тысячи двадцать седьмой год"),
        ("до 2030 года", "до две тысячи тридцатого года"),
    ],
)
def test_dates(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


def test_date_with_time_in_one_phrase() -> None:
    assert normalize_for_speech("5 марта 2026 в 15:45") == (
        "пятого марта две тысячи двадцать шестого года в пятнадцать сорок пять"
    )


@pytest.mark.parametrize("text", ["32 октября", "0 мая", "13.13", "1.5"])
def test_impossible_dates_are_not_dates(text: str) -> None:
    spoken = normalize_for_speech(text)

    assert "ого " not in f"{spoken} "
    assert_speakable(spoken)


# --- Числа -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 задачи", "две задачи"),
        ("2 встречи", "две встречи"),
        ("2 напоминания", "два напоминания"),
        ("3 дела", "три дела"),
        ("1 дело", "одно дело"),
        ("1 задача", "одна задача"),
        ("21 запись", "двадцать одна запись"),
        ("22 встречи", "двадцать две встречи"),
        ("5 задач", "пять задач"),
        ("11 задач", "одиннадцать задач"),
        ("2 новые задачи", "две новые задачи"),
        ("через 2 часа", "через два часа"),
        ("через 2 недели", "через две недели"),
        ("на 1 неделю", "на одну неделю"),
        ("в 10 утра", "в десять утра"),
        ("в 10 позвонить Ивану", "в десять позвонить Ивану"),
        ("Сделано 2 из 5.", "Сделано два из пяти."),
        ("от 1 до 3", "от одного до трёх"),
        ("из 5 задач", "из пяти задач"),
        ("с 2 задачами", "с двумя задачами"),
        ("к 2 задачам", "к двум задачам"),
        ("о 2 задачах", "о двух задачах"),
        ("Нашёл 21 запись.", "Нашёл двадцать одну запись."),
        ("Нашёл 4 записи.", "Нашёл четыре записи."),
        ("0 задач", "ноль задач"),
        ("1000 записей", "одна тысяча записей"),
    ],
)
def test_numbers_agree_with_neighbours(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,5 часа", "одна целая пять десятых часа"),
        ("0.25", "ноль целых двадцать пять сотых"),
        ("10%", "десять процентов"),
        ("1 %", "один процент"),
        ("через 1 мин.", "через одну минуту"),
        ("через 5 мин.", "через пять минут"),
        ("через 2 мин", "через две минуты"),
        ("из 5 мин.", "из пяти минут"),
        ("10 МБ", "десять мегабайт"),
        ("2 кг", "два килограмма"),
        ("100 руб.", "сто рублей"),
        ("21 ₽", "двадцать один рубль"),
        ("за 3 сек.", "за три секунды"),
    ],
)
def test_decimals_and_units(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3-й этап", "третий этап"),
        ("2-я встреча", "вторая встреча"),
        ("5-е место", "пятое место"),
        ("до 2-го числа", "до второго числа"),
        ("к 3-му", "к третьему"),
        ("в 3-м квартале", "в третьем квартале"),
        ("в 90-х", "в девяностых"),
        ("1-ю задачу", "первую задачу"),
    ],
)
def test_ordinals_with_suffix(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


# --- Латиница, аббревиатуры, ударения -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ТЗ", "тэз+э"),
        ("КП", "кэп+э"),
        ("СМС", "эсэм+эс"),
        ("Согласовать ТЗ", "Согласовать тэз+э"),
        ("CRM", "сиар+эм"),
        ("API", "эйпи+ай"),
        ("Q3", "кь+ю три"),
        ("B2B", "б+и два б+и"),
        ("Zoom", "зум"),
        ("созвон в Zoom", "созвон в зум"),
        ("Telegram", "телеграм"),
        ("e-mail", "имейл"),
        ("Notion", "ноушн"),
        ("Asana", "асана"),
        ("Chess", "чесс"),
        ("Gorky", "г+орький"),
        ("ВУЗ", "вуз"),
        ("ООН", "оон"),
        ("СРОЧНО", "срочно"),
        ("ЙОД", "йод"),
    ],
)
def test_latin_and_abbreviations(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Я Горький.", "Я Г+орький."),
        ("Горького", "Г+орького"),
        ("улица горького", "улица г+орького"),
        ("Г+орький", "Г плюс орький"),
    ],
)
def test_assistant_name_is_stressed(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


# --- Знаки ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Встреча «Планёрка»", "Встреча Планёрка"),
        ('Задача "Отчёт"', "Задача Отчёт"),
        ("Встреча — завтра", f"Встреча {EN_DASH} завтра"),
        ("Встреча - завтра", f"Встреча {EN_DASH} завтра"),
        ("кто-нибудь", "кто-нибудь"),
        ("Отчёт (черновик) готов", "Отчёт, черновик, готов"),
        ("Привет 🙂", "Привет"),
        ("🙂", ""),
        ("C++ & Java", "с+и плюс плюс и джава"),
        ("Задача №5", "Задача номер пять"),
        ("Ну...", "Ну…"),
        ("слово_с|разметкой~", "слово с разметкой"),
        ("  лишние   пробелы  ", "лишние пробелы"),
        ("—  Привет", "Привет"),
        ("строка\nвторая", "строка вторая"),
        (f"через 10{NO_BREAK_SPACE}мин.", "через десять минут"),
    ],
)
def test_symbols_and_punctuation(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


def test_empty_text_stays_empty() -> None:
    assert normalize_for_speech("") == ""


# --- Ответы ассистента из шаблонов (app.core.dialog.phrases) --------------------------------

MEETING_TOMORROW = card(EventType.MEETING, "Встреча с командой", at(TOMORROW, 15))
CALL_TODAY = card(EventType.MEETING, "Созвон по CRM", at(TODAY, 17), ends_at=at(TODAY, 18))
REPORT_TASK = card(EventType.TASK, "Согласовать ТЗ", at(TODAY, 18, 30))
PAST_MEETING = card(
    EventType.MEETING, "Встреча с Иваном", at(TODAY.replace(month=3, day=5), 15, 45)
)
UNDATED = card(EventType.TASK, "Купить 2 билета", None)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (
            phrases.created(MEETING_TOMORROW, TODAY),
            f"Встреча Встреча с командой {EN_DASH} завтра, двадцать седьмого октября, "
            "в пятнадцать ноль-ноль.",
        ),
        (
            phrases.search_latest_past(PAST_MEETING, TODAY),
            "Последняя встреча Встреча с Иваном была пятого марта две тысячи двадцать шестого "
            "года в пятнадцать сорок пять.",
        ),
        (
            phrases.list_summary(
                [MEETING_TOMORROW, CALL_TODAY, REPORT_TASK], day_period(TODAY, "сегодня"), NOW, None
            ),
            "Сегодня у вас три дела: две встречи и задача. "
            f"Ближайшее {EN_DASH} Созвон по сиар+эм сегодня в семнадцать ноль-ноль.",
        ),
        (
            phrases.conflict_question([CALL_TODAY], phrases.ADD_ANYWAY),
            "В это время уже стоит Созвон по сиар+эм, с семнадцати ноль-ноль до восемнадцати "
            "ноль-ноль. Всё равно добавить?",
        ),
        (
            phrases.choice_out_of_range(3),
            f"Такого варианта нет {EN_DASH} назовите номер от одного до трёх.",
        ),
        (
            phrases.search_found(21, REPORT_TASK, TODAY),
            f"Нашёл двадцать одну запись. Больше всего подходит {EN_DASH} задача Согласовать "
            "тэз+э, сегодня, двадцать шестого октября, в восемнадцать тридцать.",
        ),
        (
            phrases.rescheduled(
                card(EventType.MEETING, "Планёрка", at(TODAY + timedelta(days=17), 8, 45)), TODAY
            ),
            "Перенёс встречу Планёрка на двенадцатое ноября в восемь сорок пять.",
        ),
        (phrases.search_undated(UNDATED), f"Нашёл задачу Купить два билета {EN_DASH} без срока."),
        (
            phrases.choice_text(Action.DELETE, phrases.TYPE_NOUNS[EventType.MEETING], 3, 3),
            "Нашёл три встречи. Какую удалить?",
        ),
    ],
)
def test_assistant_replies(reply: str, expected: str) -> None:
    assert normalize_for_speech(reply) == expected


def test_week_summary_with_done_items() -> None:
    done = card(EventType.TASK, "Отчёт", at(TODAY, 9), status=EventStatus.DONE)
    monday = at(TODAY, 0)
    week = Period(start=monday, end=monday + timedelta(days=7), label="на этой неделе")

    spoken = normalize_for_speech(phrases.list_summary([done, MEETING_TOMORROW], week, NOW, None))

    assert spoken.startswith("На этой неделе у вас два дела: встреча и задача.")
    assert "Сделано один из двух." in spoken
    assert_speakable(spoken)


@pytest.mark.parametrize(
    "reply",
    [
        phrases.SMALLTALK,
        phrases.NOT_UNDERSTOOD,
        phrases.OFF_TOPIC,
        phrases.TARGET_UNCLEAR,
        phrases.SEARCH_NOTHING,
        phrases.MEETING_TIME_QUESTION,
        phrases.delete_question(MEETING_TOMORROW, TODAY),
        phrases.undo_reverted(REPORT_TASK, TODAY),
        phrases.schedule_text(
            card(
                EventType.MEETING,
                "Обед",
                at(TOMORROW, 13),
                ends_at=at(TOMORROW, 14, 30),
            ),
            TODAY,
        ),
    ],
)
def test_every_template_becomes_speakable(reply: str) -> None:
    assert_speakable(normalize_for_speech(reply))


def test_example_phrases_read_numbers_as_words() -> None:
    spoken = normalize_for_speech(phrases.SMALLTALK)

    assert "Я Г+орький" in spoken
    assert "в десять позвонить Ивану" in spoken


# --- Деление на части -------------------------------------------------------------------------


def test_short_text_is_one_chunk() -> None:
    assert speech_chunks("Привет. Пока.") == ["Привет. Пока."]


def test_sentences_are_packed_up_to_limit() -> None:
    assert speech_chunks("Раз два. Три. Четыре пять.", limit=13) == [
        "Раз два. Три.",
        "Четыре пять.",
    ]


def test_long_sentence_is_split_by_words() -> None:
    sentence = " ".join(["слово"] * 300) + "."

    chunks = speech_chunks(sentence)

    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert " ".join(chunks) == sentence


def test_word_longer_than_limit_is_cut() -> None:
    assert speech_chunks("а" * 15, limit=10) == ["а" * 10]


@pytest.mark.parametrize("text", ["", "   ", "…", "... ? !"])
def test_text_without_letters_has_no_chunks(text: str) -> None:
    assert speech_chunks(text) == []
