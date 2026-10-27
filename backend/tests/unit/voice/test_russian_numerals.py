"""Числа словами: падежи и род, формы после числа, время и даты."""

import pytest

from app.voice.latin_reading import (
    CYRILLIC_LETTER_NAMES,
    LATIN_LETTER_NAMES,
    spell_letters,
    transliterate,
)
from app.voice.russian_numerals import (
    Case,
    CountedNoun,
    Gender,
    cardinal,
    date_words,
    ordinal,
    plural_form_index,
    time_words,
)

MINUTE = CountedNoun("минута", ("минута", "минуты", "минут"), Gender.FEMININE)


@pytest.mark.parametrize(
    ("count", "index"),
    [
        (0, 2),
        (1, 0),
        (2, 1),
        (4, 1),
        (5, 2),
        (11, 2),
        (12, 2),
        (14, 2),
        (20, 2),
        (21, 0),
        (22, 1),
        (25, 2),
        (101, 0),
        (111, 2),
        (1_000, 2),
    ],
)
def test_form_after_number(count: int, index: int) -> None:
    assert plural_form_index(count) == index


@pytest.mark.parametrize(
    ("count", "case", "expected"),
    [
        (1, Case.NOMINATIVE, "минута"),
        (1, Case.ACCUSATIVE, "минуту"),
        (2, Case.ACCUSATIVE, "минуты"),
        (5, Case.NOMINATIVE, "минут"),
        (5, Case.GENITIVE, "минут"),
        (2, Case.DATIVE, "минутам"),
        (2, Case.INSTRUMENTAL, "минутами"),
        (21, Case.PREPOSITIONAL, "минуте"),
    ],
)
def test_counted_noun_agrees_with_number(count: int, case: Case, expected: str) -> None:
    assert MINUTE.agreed(count, case) == expected


@pytest.mark.parametrize(
    ("number", "case", "gender", "expected"),
    [
        (2, Case.NOMINATIVE, Gender.FEMININE, "две"),
        (2, Case.NOMINATIVE, Gender.NEUTER, "два"),
        (1, Case.NOMINATIVE, Gender.NEUTER, "одно"),
        (21, Case.ACCUSATIVE, Gender.FEMININE, "двадцать одну"),
        (2, Case.ACCUSATIVE, Gender.FEMININE, "две"),
        (3, Case.GENITIVE, Gender.MASCULINE, "трёх"),
        (2, Case.INSTRUMENTAL, Gender.FEMININE, "двумя"),
    ],
)
def test_cardinal_is_inanimate(number: int, case: Case, gender: Gender, expected: str) -> None:
    assert cardinal(number, case, gender) == expected


def test_plural_ordinal() -> None:
    assert ordinal(90, Case.GENITIVE, plural=True) == "девяностых"


@pytest.mark.parametrize(
    ("hour", "minute", "case", "expected"),
    [
        (15, 0, Case.NOMINATIVE, "пятнадцать ноль-ноль"),
        (15, 0, Case.GENITIVE, "пятнадцати ноль-ноль"),
        (16, 30, Case.GENITIVE, "шестнадцати тридцати"),
        (10, 0, Case.DATIVE, "десяти ноль-ноль"),
        (8, 45, Case.NOMINATIVE, "восемь сорок пять"),
        (9, 5, Case.NOMINATIVE, "девять ноль пять"),
        (9, 5, Case.GENITIVE, "девяти ноль пяти"),
        (1, 0, Case.NOMINATIVE, "час ноль-ноль"),
        (1, 15, Case.GENITIVE, "часа пятнадцати"),
        (0, 0, Case.NOMINATIVE, "полночь"),
        (0, 0, Case.GENITIVE, "полуночи"),
        (0, 30, Case.NOMINATIVE, "ноль тридцать"),
        (12, 1, Case.NOMINATIVE, "двенадцать ноль одна"),
        (23, 59, Case.NOMINATIVE, "двадцать три пятьдесят девять"),
    ],
)
def test_time_words(hour: int, minute: int, case: Case, expected: str) -> None:
    assert time_words(hour, minute, case) == expected


@pytest.mark.parametrize(
    ("day", "month", "year", "case", "expected"),
    [
        (27, 10, None, Case.GENITIVE, "двадцать седьмого октября"),
        (12, 11, None, Case.ACCUSATIVE, "двенадцатое ноября"),
        (12, 11, None, Case.DATIVE, "двенадцатому ноября"),
        (1, 1, 2027, Case.GENITIVE, "первого января две тысячи двадцать седьмого года"),
        (3, 2, 2000, Case.ACCUSATIVE, "третье февраля двухтысячного года"),
    ],
)
def test_date_words(day: int, month: int, year: int | None, case: Case, expected: str) -> None:
    assert date_words(day, month, year, case) == expected


@pytest.mark.parametrize(
    ("letters", "names", "expected"),
    [
        ("ТЗ", CYRILLIC_LETTER_NAMES, "тэз+э"),
        ("МВД", CYRILLIC_LETTER_NAMES, "эмвэд+э"),
        ("HR", LATIN_LETTER_NAMES, "эйч+ар"),
        ("X", LATIN_LETTER_NAMES, "+икс"),
    ],
)
def test_spelled_letters_have_one_stress_on_last(
    letters: str, names: dict[str, str], expected: str
) -> None:
    spoken = spell_letters(letters, names)

    assert spoken == expected
    assert spoken.count("+") == 1


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Zoom", "зум"),
        ("ZOOM", "зум"),
        ("Asana", "асана"),
        ("Trello", "трелло"),
        ("Miro", "миро"),
        ("Shop", "шоп"),
        ("Center", "сентер"),
        ("Box", "бокс"),
        ("Jet", "джет"),
        ("Yandex", "яндекс"),
    ],
)
def test_transliteration(word: str, expected: str) -> None:
    assert transliterate(word) == expected
