"""Подготовка текста к озвучке Silero v4_ru.

Silero читает только кириллицу и знаки препинания: цифры, латиница, кавычки и эмодзи
пропадают молча («В 15:00 у вас 2 задачи» звучит как «В у вас задачи»). Поэтому ответ
ассистента сначала переводится в слова:

- время: «в 15:00» → «в пятнадцать ноль-ноль», «8:45» → «восемь сорок пять»,
  «с 15:00 до 16:30» и диапазон «15:00-16:00» → родительный падеж;
- даты: «27 октября» → «двадцать седьмого октября», «на 12 ноября» → «на двенадцатое ноября»,
  «5 марта 2026» → «пятого марта две тысячи двадцать шестого года», «27.10» — так же;
- числа согласуются с соседними словами: «2 задачи» → «две задачи», «из 5» → «из пяти»,
  «с 2 задачами» → «с двумя задачами», «через 1 мин.» → «через одну минуту», «3-й» → «третий»;
- аббревиатуры и латиница — `app.voice.latin_reading`: «ТЗ» → «тэз+э», «Zoom» → «зум»;
- «Горький» — с ударением «Г+орький»; кавычки, скобки и эмодзи убираются,
  длинное тире становится коротким (его Silero понимает как паузу).

Знак «+» перед гласной — ударение в разметке Silero, поэтому «+» из исходного текста
заменяется словом «плюс».
"""

import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.voice.latin_reading import STRESS_MARK, read_latin, spell_abbreviations
from app.voice.russian_numerals import (
    MONTHS_GENITIVE,
    Case,
    CountedNoun,
    Gender,
    cardinal,
    date_words,
    decimal,
    morph,
    ordinal,
    time_words,
)

MAX_CHUNK_CHARS = 250
"""Сколько символов Silero озвучивает за раз. Около 1000 модель падает, а память растёт быстрее
длины куска: пик RSS ~1,1 ГБ на 250 символов и ~2,6 ГБ на 500 (замер на 48 кГц)."""

EN_DASH = "\u2013"
"""Короткое тире — единственное тире в алфавите Silero, читается паузой."""
EM_DASH = "\u2014"
MINUS_SIGN = "\u2212"
ELLIPSIS = "\u2026"

CASE_AFTER_PREPOSITION: Final[Mapping[str, Case]] = MappingProxyType(
    {
        **dict.fromkeys(
            ("с", "со", "до", "от", "из", "после", "около", "без", "для", "у", "кроме"),
            Case.GENITIVE,
        ),
        **dict.fromkeys(("к", "ко"), Case.DATIVE),
        **dict.fromkeys(("в", "во", "на", "за", "через", "про", "под", "по"), Case.ACCUSATIVE),
        **dict.fromkeys(("перед", "между", "над"), Case.INSTRUMENTAL),
        **dict.fromkeys(("о", "об", "при"), Case.PREPOSITIONAL),
    }
)
_PREPOSITION = r"(?:(?P<prep>\b(?:" + "|".join(CASE_AFTER_PREPOSITION) + r"))\s+)?"
"""Необязательный предлог прямо перед числом: от него зависит падеж."""


def _case_after(preposition: str | None) -> Case:
    if preposition is None:
        return Case.NOMINATIVE
    return CASE_AFTER_PREPOSITION.get(preposition.lower(), Case.NOMINATIVE)


def _with_preposition(preposition: str | None, words: str) -> str:
    return f"{preposition} {words}" if preposition else words


# --- Служебные символы --------------------------------------------------------------------

_SYMBOL_WORDS: Final[Mapping[str, str]] = MappingProxyType(
    {"+": " плюс ", "&": " и ", "№": " номер ", "\u00a0": " ", "\u202f": " "}
)
"""Символы, которые нужно произнести, и неразрывные пробелы."""
_SILERO_SERVICE_SYMBOLS_PATTERN = re.compile(r"[_~|]")
"""Символы, которые Silero понимает как разметку."""


def _replace_symbols(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for symbol, words in _SYMBOL_WORDS.items():
        text = text.replace(symbol, words)
    return _SILERO_SERVICE_SYMBOLS_PATTERN.sub(" ", text).replace("...", ELLIPSIS)


# --- Время ---------------------------------------------------------------------------------

_TIME = r"(?<![\d:.,])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])"
_DASHES = rf"[{EN_DASH}{EM_DASH}-]"
_TIME_RANGE_PATTERN = re.compile(rf"(?P<start>{_TIME})\s*{_DASHES}\s*(?P<end>{_TIME})")
_TIME_PATTERN = re.compile(rf"{_PREPOSITION}(?P<time>{_TIME})", re.IGNORECASE)


def _parse_time(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def _expand_times(text: str) -> str:
    text = _TIME_RANGE_PATTERN.sub(_time_range_words, text)
    return _TIME_PATTERN.sub(_time_match_words, text)


def _time_range_words(match: re.Match[str]) -> str:
    start = time_words(*_parse_time(match["start"]), Case.GENITIVE)
    end = time_words(*_parse_time(match["end"]), Case.GENITIVE)
    return f"с {start} до {end}"


def _time_match_words(match: re.Match[str]) -> str:
    case = _case_after(match["prep"])
    if case is Case.ACCUSATIVE:
        case = Case.NOMINATIVE  # «в 21:21» — «в двадцать один двадцать одна», не «одну»
    return _with_preposition(match["prep"], time_words(*_parse_time(match["time"]), case))


# --- Даты ----------------------------------------------------------------------------------

_DATE_PATTERN = re.compile(
    rf"{_PREPOSITION}(?<!\d)(?P<day>[12]\d|3[01]|[1-9])\s+(?P<month>{'|'.join(MONTHS_GENITIVE)})"
    r"(?:\s+(?P<year>[12]\d{3})(?:\s+(?:года|году|год)\b|\s*г\.)?)?(?!\w)",
    re.IGNORECASE,
)
_NUMERIC_DATE_PATTERN = re.compile(
    r"(?<![\d.,])(?P<day>[12]\d|3[01]|0?[1-9])\.(?P<month>0[1-9]|1[0-2])"
    r"(?:\.(?P<year>\d{4}|\d{2}))?(?![\d.,]\d)"
)
_YEAR_PATTERN = re.compile(r"(?<![\d.,])(?P<year>[12]\d{3})\s+(?P<noun>году|года|годом|год)\b")
_YEAR_NOUN_CASES: Final[Mapping[str, Case]] = MappingProxyType(
    {
        "год": Case.NOMINATIVE,
        "года": Case.GENITIVE,
        "году": Case.PREPOSITIONAL,
        "годом": Case.INSTRUMENTAL,
    }
)
_DATE_CASES = frozenset({Case.ACCUSATIVE, Case.DATIVE})
"""«на 12 ноября» → «на двенадцатое», «к 12 ноября» → «к двенадцатому»; иначе родительный."""
CENTURY = 2000


def _expand_dates(text: str) -> str:
    text = _NUMERIC_DATE_PATTERN.sub(_numeric_date_as_text, text)
    text = _DATE_PATTERN.sub(_date_match_words, text)
    return _YEAR_PATTERN.sub(_year_match_words, text)


def _numeric_date_as_text(match: re.Match[str]) -> str:
    """«27.10» → «27 октября», «05.03.26» → «5 марта 2026»: дальше как обычная дата."""
    words = f"{int(match['day'])} {MONTHS_GENITIVE[int(match['month']) - 1]}"
    year = match["year"]
    if year is None:
        return words
    full_year = int(year) + CENTURY if len(year) == 2 else int(year)
    return f"{words} {full_year}"


def _date_match_words(match: re.Match[str]) -> str:
    case = _case_after(match["prep"])
    if case not in _DATE_CASES:
        case = Case.GENITIVE
    month = MONTHS_GENITIVE.index(match["month"].lower()) + 1
    year = int(match["year"]) if match["year"] else None
    return _with_preposition(match["prep"], date_words(int(match["day"]), month, year, case))


def _year_match_words(match: re.Match[str]) -> str:
    noun = match["noun"]
    return f"{ordinal(int(match['year']), _YEAR_NOUN_CASES[noun])} {noun}"


# --- Числа ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OrdinalForm:
    case: Case
    gender: Gender = Gender.MASCULINE
    plural: bool = False


_ORDINAL_SUFFIXES: Final[Mapping[str, _OrdinalForm]] = MappingProxyType(
    {
        **dict.fromkeys(("й", "ый", "ий", "ой"), _OrdinalForm(Case.NOMINATIVE)),
        **dict.fromkeys(("я", "ая"), _OrdinalForm(Case.NOMINATIVE, Gender.FEMININE)),
        **dict.fromkeys(("е", "ое"), _OrdinalForm(Case.NOMINATIVE, Gender.NEUTER)),
        **dict.fromkeys(("ые", "ие"), _OrdinalForm(Case.NOMINATIVE, plural=True)),
        **dict.fromkeys(("го", "ого"), _OrdinalForm(Case.GENITIVE)),
        **dict.fromkeys(("му", "ому"), _OrdinalForm(Case.DATIVE)),
        **dict.fromkeys(("м", "ом", "ем"), _OrdinalForm(Case.PREPOSITIONAL)),
        **dict.fromkeys(("ым", "им"), _OrdinalForm(Case.INSTRUMENTAL)),
        **dict.fromkeys(("ю", "ую"), _OrdinalForm(Case.ACCUSATIVE, Gender.FEMININE)),
        **dict.fromkeys(("х", "ых", "их"), _OrdinalForm(Case.GENITIVE, plural=True)),
        **dict.fromkeys(("ми", "ыми"), _OrdinalForm(Case.INSTRUMENTAL, plural=True)),
    }
)
"""Окончание после дефиса → форма порядкового: «3-й» — «третий», «в 90-х» — «девяностых»."""
_ORDINAL_PATTERN = re.compile(
    r"(?<![\d.,])(?P<number>\d+)-(?P<suffix>"
    + "|".join(sorted(_ORDINAL_SUFFIXES, key=len, reverse=True))
    + r")(?!\w)"
)

_MINUTE = CountedNoun("минута", ("минута", "минуты", "минут"), Gender.FEMININE)
_HOUR = CountedNoun("час", ("час", "часа", "часов"), Gender.MASCULINE)
_SECOND = CountedNoun("секунда", ("секунда", "секунды", "секунд"), Gender.FEMININE)
_RUBLE = CountedNoun("рубль", ("рубль", "рубля", "рублей"), Gender.MASCULINE)
UNITS: Final[Mapping[str, CountedNoun]] = MappingProxyType(
    {
        "%": CountedNoun("процент", ("процент", "процента", "процентов"), Gender.MASCULINE),
        "мин.": _MINUTE,
        "мин": _MINUTE,
        "ч.": _HOUR,
        "сек.": _SECOND,
        "сек": _SECOND,
        "руб.": _RUBLE,
        "руб": _RUBLE,
        "₽": _RUBLE,
        "мб": CountedNoun("мегабайт", ("мегабайт", "мегабайта", "мегабайт"), Gender.MASCULINE),
        "гб": CountedNoun("гигабайт", ("гигабайт", "гигабайта", "гигабайт"), Gender.MASCULINE),
        "кг": CountedNoun(
            "килограмм", ("килограмм", "килограмма", "килограммов"), Gender.MASCULINE
        ),
        "км": CountedNoun("километр", ("километр", "километра", "километров"), Gender.MASCULINE),
    }
)
"""Сокращения единиц после числа (ключи в нижнем регистре)."""
_UNIT_ALTERNATIVES = "|".join(re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True))
_NUMBER_PATTERN = re.compile(
    rf"{_PREPOSITION}(?<![\d.,])(?P<integer>\d+)(?:[.,](?P<fraction>\d+))?"
    rf"(?:\s*(?P<unit>{_UNIT_ALTERNATIVES})(?!\w))?",
    re.IGNORECASE,
)
_NEXT_WORDS_PATTERN = re.compile(r"\s*([а-яё]+)(?:\s+([а-яё]+))?", re.IGNORECASE)
_CASE_OF_NOUN: Final[Mapping[str, Case]] = MappingProxyType(
    {
        "accs": Case.ACCUSATIVE,
        "datv": Case.DATIVE,
        "ablt": Case.INSTRUMENTAL,
        "loct": Case.PREPOSITIONAL,
    }
)
"""Падежи существительного, в которых с ним согласуется и число: «с 2 задачами» → «с двумя».

Родительного нет: в «5 задач» число в именительном, хотя существительное в родительном."""
_GENDERS: Final[Mapping[str, Gender]] = MappingProxyType(
    {"masc": Gender.MASCULINE, "femn": Gender.FEMININE, "neut": Gender.NEUTER}
)
ACCUSATIVE_VERBS = frozenset({"нашёл", "нашел"})
"""Глаголы ответов, после которых число в винительном: «Нашёл 21 запись» → «двадцать одну»."""


@dataclass(frozen=True, slots=True)
class _NounContext:
    """Что число узнаёт от существительного после себя: род и (не всегда) падеж."""

    gender: Gender = Gender.MASCULINE
    case: Case | None = None


def _noun_after(text: str) -> _NounContext:
    """Существительное сразу после числа или после одного прилагательного («2 новые задачи»)."""
    match = _NEXT_WORDS_PATTERN.match(text)
    if match is None:
        return _NounContext()
    for word in match.groups():
        if word is None:
            break
        parse = morph().parse(word)[0]
        if "NOUN" in parse.tag:
            return _NounContext(
                gender=_GENDERS.get(str(parse.tag.gender), Gender.MASCULINE),
                case=_CASE_OF_NOUN.get(str(parse.tag.case)),
            )
        if "ADJF" not in parse.tag:
            break
    return _NounContext()


def _follows_accusative_verb(text_before: str) -> bool:
    words = text_before.split()
    return bool(words) and words[-1].lower() in ACCUSATIVE_VERBS


def _expand_numbers(text: str) -> str:
    text = _ORDINAL_PATTERN.sub(_ordinal_match_words, text)
    return _NUMBER_PATTERN.sub(lambda match: _number_match_words(match, text), text)


def _ordinal_match_words(match: re.Match[str]) -> str:
    form = _ORDINAL_SUFFIXES[match["suffix"]]
    return ordinal(int(match["number"]), form.case, form.gender, plural=form.plural)


def _number_match_words(match: re.Match[str], text: str) -> str:
    preposition = match["prep"]
    if match["fraction"] is not None:
        return _with_preposition(preposition, decimal(f"{match['integer']}.{match['fraction']}"))
    count = int(match["integer"])
    case = _case_after(preposition)
    if match["unit"] is not None:
        unit = UNITS[match["unit"].lower()]
        words = f"{cardinal(count, case, unit.gender)} {unit.agreed(count, case)}"
        return _with_preposition(preposition, words)
    noun = _noun_after(text[match.end() :])
    if noun.case is not None:
        case = noun.case
    elif preposition is None and _follows_accusative_verb(text[: match.start()]):
        case = Case.ACCUSATIVE
    return _with_preposition(preposition, cardinal(count, case, noun.gender))


# --- Ударения и пунктуация -----------------------------------------------------------------

_STRESSES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"(?<![\w+])([Гг])(?=орьк)"), rf"\1{STRESS_MARK}"),
)
"""Ударения, которые нельзя оставить на волю Silero: «Горький» — имя ассистента."""

_QUOTES_PATTERN = re.compile(r"[«»„“”\"'`\u2018\u2019]")
_OPENING_BRACKETS_PATTERN = re.compile(r"\s*[(\[{]\s*")
_CLOSING_BRACKETS_PATTERN = re.compile(r"\s*[)\]}]")
_LONG_DASH_PATTERN = re.compile(rf"\s*[{EM_DASH}{MINUS_SIGN}]\s*|\s+[-{EN_DASH}]\s+")
_UNSPEAKABLE_PATTERN = re.compile(rf"[^а-яёА-ЯЁ0-9+,.!?:;{EN_DASH}{ELLIPSIS}\s-]")
_LEFTOVER_DIGITS_PATTERN = re.compile(r"\d+")
_SPACES_PATTERN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(rf"\s+([,.!?:;{ELLIPSIS}])")
_REPEATED_COMMAS_PATTERN = re.compile(r",(?:\s*,)+")
_COMMA_BEFORE_STOP_PATTERN = re.compile(rf",\s*([.!?:;{ELLIPSIS}])")
_LEADING_PUNCTUATION_PATTERN = re.compile(rf"^[\s,.:;{EN_DASH}-]+")


def _stress_words(text: str) -> str:
    for pattern, replacement in _STRESSES:
        text = pattern.sub(replacement, text)
    return text


def _clean_punctuation(text: str) -> str:
    text = _QUOTES_PATTERN.sub("", text)
    text = _OPENING_BRACKETS_PATTERN.sub(", ", text)
    text = _CLOSING_BRACKETS_PATTERN.sub(",", text)
    text = _LONG_DASH_PATTERN.sub(f" {EN_DASH} ", text)
    text = _UNSPEAKABLE_PATTERN.sub(" ", text)
    text = _LEFTOVER_DIGITS_PATTERN.sub(lambda match: f" {cardinal(int(match[0]))} ", text)
    text = _SPACES_PATTERN.sub(" ", text)
    text = _SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", text)
    text = _REPEATED_COMMAS_PATTERN.sub(",", text)
    text = _COMMA_BEFORE_STOP_PATTERN.sub(r"\1", text)
    return _LEADING_PUNCTUATION_PATTERN.sub("", text).strip()


_STEPS: Final[tuple[Callable[[str], str], ...]] = (
    _replace_symbols,
    _expand_times,
    _expand_dates,
    read_latin,
    _expand_numbers,
    spell_abbreviations,
    _stress_words,
    _clean_punctuation,
)
"""Порядок важен: время и даты — раньше чисел, латиница («Q3») — раньше чисел,
ударения — после транслитерации («Gorky» → «горький» → «г+орький»)."""


def normalize_for_speech(text: str) -> str:
    """Текст, который Silero прочтёт целиком: числа, даты и латиница — словами."""
    for step in _STEPS:
        text = step(text)
    return text


# --- Деление на части для синтеза -------------------------------------------------------------

_SENTENCE_END_PATTERN = re.compile(rf"(?<=[.!?{ELLIPSIS}])\s+")
_LETTER_PATTERN = re.compile(r"[а-яё]", re.IGNORECASE)
"""Кусок без букв Silero не озвучивает, а падает."""


def speech_chunks(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Куски с буквами не длиннее `limit`: целые предложения, слишком длинное — по словам."""
    chunks: list[str] = []
    current = ""
    for piece in _pieces(text, limit):
        candidate = f"{current} {piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
            continue
        chunks.append(current)
        current = piece
    if current:
        chunks.append(current)
    return chunks


def _pieces(text: str, limit: int) -> Iterator[str]:
    for sentence in _SENTENCE_END_PATTERN.split(text.strip()):
        if not _LETTER_PATTERN.search(sentence):
            continue
        if len(sentence) <= limit:
            yield sentence
            continue
        yield from _word_pieces(sentence, limit)


def _word_pieces(sentence: str, limit: int) -> Iterator[str]:
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            yield current
        current = word[:limit]
    if current:
        yield current
