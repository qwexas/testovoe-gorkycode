"""числа словами по-русски в нужном падеже и роде: для озвучки времени, дат и количеств."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from types import MappingProxyType
from typing import Final

import pymorphy3  # type: ignore[import-untyped]
from num2words import num2words  # type: ignore[import-untyped]


class Case(StrEnum):
    """Падеж числительного; значения совпадают с параметром `case` у num2words."""

    NOMINATIVE = "nominative"
    GENITIVE = "genitive"
    DATIVE = "dative"
    ACCUSATIVE = "accusative"
    INSTRUMENTAL = "instrumental"
    PREPOSITIONAL = "prepositional"


class Gender(StrEnum):
    """Род числительного; значения совпадают с параметром `gender` у num2words."""

    MASCULINE = "m"
    FEMININE = "f"
    NEUTER = "n"


OPENCORPORA_CASES: Final[Mapping[Case, str]] = MappingProxyType(
    {
        Case.NOMINATIVE: "nomn",
        Case.GENITIVE: "gent",
        Case.DATIVE: "datv",
        Case.ACCUSATIVE: "accs",
        Case.INSTRUMENTAL: "ablt",
        Case.PREPOSITIONAL: "loct",
    }
)
"""граммемы падежей в pymorphy3."""


@cache
def morph() -> pymorphy3.MorphAnalyzer:
    """общий анализатор: словари грузятся один раз, дальше только читаются."""
    return pymorphy3.MorphAnalyzer()


def cardinal(number: int, case: Case = Case.NOMINATIVE, gender: Gender = Gender.MASCULINE) -> str:
    """«две», «пяти», «двадцать одну» — количественное числительное (неодушевлённое)."""
    words: str = num2words(number, lang="ru", case=case.value, gender=gender.value, animate=False)
    return words


def ordinal(
    number: int,
    case: Case = Case.NOMINATIVE,
    gender: Gender = Gender.MASCULINE,
    *,
    plural: bool = False,
) -> str:
    """«двадцать седьмого», «третье», «девяностых» — порядковое числительное."""
    words: str = num2words(
        number,
        lang="ru",
        to="ordinal",
        case=case.value,
        gender=gender.value,
        plural=plural,
        animate=False,
    )
    return words


def decimal(text: str) -> str:
    """«1,5» → «одна целая пять десятых»."""
    words: str = num2words(float(text.replace(",", ".")), lang="ru")
    return words


def takes_singular(count: int) -> bool:
    """1, 21, 101 — «одна задача», «двадцать одна задача», но 11 — «одиннадцать задач»."""
    return count % 10 == 1 and count % 100 != 11


def plural_form_index(count: int) -> int:
    """номер формы слова после числа: 0 — «задача» (1, 21), 1 — «задачи» (2, 3, 4, 22),
    2 — «задач» (0, от 5 до 20, 25)."""
    last_two = count % 100
    last = last_two % 10
    if 11 <= last_two <= 14 or last == 0 or last >= 5:
        return 2
    return 0 if takes_singular(count) else 1


def inflected(lemma: str, grammemes: frozenset[str]) -> str | None:
    """форма слова с граммемами pymorphy3: («минута», {"gent", "plur"}) → «минут»."""
    form = morph().parse(lemma)[0].inflect(set(grammemes))
    return None if form is None else str(form.word)


@dataclass(frozen=True, slots=True)
class CountedNoun:
    """единица после числа, которую нужно согласовать: «5 мин.» → «пять минут»."""

    lemma: str
    forms: tuple[str, str, str]
    """формы после 1, после 2, 3, 4 и после 5: «минута», «минуты», «минут»."""
    gender: Gender

    def agreed(self, count: int, case: Case) -> str:
        """«одну минуту», «две минуты», «пяти минут»."""
        if case is Case.ACCUSATIVE and takes_singular(count):
            return inflected(self.lemma, frozenset({"accs", "sing"})) or self.forms[0]
        if case in (Case.NOMINATIVE, Case.ACCUSATIVE):
            return self.forms[plural_form_index(count)]
        number = "sing" if takes_singular(count) else "plur"
        grammemes = frozenset({OPENCORPORA_CASES[case], number})
        return inflected(self.lemma, grammemes) or self.forms[2]


ZERO = "ноль"
ROUND_HOUR = "ноль-ноль"
_MIDNIGHT: Final[Mapping[Case, str]] = MappingProxyType(
    {
        Case.NOMINATIVE: "полночь",
        Case.ACCUSATIVE: "полночь",
        Case.GENITIVE: "полуночи",
        Case.DATIVE: "полуночи",
        Case.INSTRUMENTAL: "полуночью",
        Case.PREPOSITIONAL: "полуночи",
    }
)
_ONE_HOUR: Final[Mapping[Case, str]] = MappingProxyType(
    {
        Case.NOMINATIVE: "час",
        Case.ACCUSATIVE: "час",
        Case.GENITIVE: "часа",
        Case.DATIVE: "часу",
        Case.INSTRUMENTAL: "часом",
        Case.PREPOSITIONAL: "часе",
    }
)


def time_words(hour: int, minute: int, case: Case = Case.NOMINATIVE) -> str:
    """«пятнадцать ноль-ноль», «восемь сорок пять», «девять ноль пять», «час тридцать».

    Минуты — женского рода («девять двадцать одна»); «ноль» и «ноль-ноль» не склоняются.
    """
    if hour == 0 and minute == 0:
        return _MIDNIGHT[case]
    if hour == 0:
        hour_text = ZERO
    elif hour == 1:
        hour_text = _ONE_HOUR[case]
    else:
        hour_text = cardinal(hour, case)
    if minute == 0:
        return f"{hour_text} {ROUND_HOUR}"
    minute_text = cardinal(minute, case, Gender.FEMININE)
    return f"{hour_text} {ZERO} {minute_text}" if minute < 10 else f"{hour_text} {minute_text}"


MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def date_words(day: int, month: int, year: int | None = None, case: Case = Case.GENITIVE) -> str:
    """«двадцать седьмого октября», «пятого марта две тысячи двадцать шестого года»."""
    words = f"{ordinal(day, case, Gender.NEUTER)} {MONTHS_GENITIVE[month - 1]}"
    if year is None:
        return words
    return f"{words} {ordinal(year, Case.GENITIVE)} года"
