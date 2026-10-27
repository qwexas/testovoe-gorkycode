"""Чтение латиницы и аббревиатур по-русски: Silero не знает латинских букв, а «ТЗ» читает
как одно невнятное слово."""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.voice.russian_numerals import cardinal

STRESS_MARK = "+"
"""Ударение в разметке Silero: «+» перед ударной гласной."""

LATIN_WORDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "zoom": "зум",
        "google": "гугл",
        "gmail": "джимейл",
        "telegram": "телеграм",
        "whatsapp": "вотсап",
        "slack": "слак",
        "skype": "скайп",
        "teams": "тимс",
        "excel": "эксель",
        "word": "ворд",
        "powerpoint": "пауэрпоинт",
        "jira": "джира",
        "figma": "фигма",
        "notion": "ноушн",
        "github": "гитхаб",
        "email": "имейл",
        "e-mail": "имейл",
        "ok": "окей",
        "okay": "окей",
        "wifi": "вайфай",
        "wi-fi": "вайфай",
        "iphone": "айфон",
        "android": "андроид",
        "yandex": "яндекс",
        "gorky": "горький",
        "online": "онлайн",
        "offline": "офлайн",
        "deadline": "дедлайн",
        "meeting": "митинг",
        "call": "колл",
        "demo": "демо",
        "sprint": "спринт",
    }
)
"""Слова, которые транслитерация прочла бы неверно."""

LATIN_LETTER_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "A": "+эй",
        "B": "б+и",
        "C": "с+и",
        "D": "д+и",
        "E": "+и",
        "F": "+эф",
        "G": "дж+и",
        "H": "+эйч",
        "I": "+ай",
        "J": "дж+ей",
        "K": "к+ей",
        "L": "+эл",
        "M": "+эм",
        "N": "+эн",
        "O": "+оу",
        "P": "п+и",
        "Q": "кь+ю",
        "R": "+ар",
        "S": "+эс",
        "T": "т+и",
        "U": "+ю",
        "V": "в+и",
        "W": "дабл+ю",
        "X": "+икс",
        "Y": "у+ай",
        "Z": "з+ед",
    }
)
CYRILLIC_LETTER_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "А": "+а",
        "Б": "б+э",
        "В": "в+э",
        "Г": "г+э",
        "Д": "д+э",
        "Е": "+е",
        "Ё": "+ё",
        "Ж": "ж+э",
        "З": "з+э",
        "И": "+и",
        "К": "к+э",
        "Л": "+эл",
        "М": "+эм",
        "Н": "+эн",
        "О": "+о",
        "П": "п+э",
        "Р": "+эр",
        "С": "+эс",
        "Т": "т+э",
        "У": "+у",
        "Ф": "+эф",
        "Х": "х+а",
        "Ц": "ц+э",
        "Ч": "ч+э",
        "Ш": "ш+а",
        "Щ": "щ+а",
        "Ы": "+ы",
        "Э": "+э",
        "Ю": "+ю",
        "Я": "+я",
    }
)
"""Названия букв, как их говорят в аббревиатурах: «КП» — «кэпэ», а не «капэ».

Й, Ъ и Ь в аббревиатурах не встречаются: слово капсом с ними читается как слово."""

WORD_ACRONYMS = frozenset({"ВУЗ", "МИД", "ГОСТ", "ЗАГС", "ООН", "НАТО", "МКАД", "ГУМ", "ЦУМ"})
"""Аббревиатуры, которые читаются словом, а не по буквам."""
MAX_SPELLED_LETTERS = 4
"""Слово капсом длиннее — скорее выделение («СРОЧНО»), чем аббревиатура."""
MAX_SPELLED_LATIN_LETTERS = 5

_TRANSLITERATION: Final[tuple[tuple[str, str], ...]] = (
    ("sch", "ш"),
    ("tch", "ч"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ph", "ф"),
    ("th", "т"),
    ("ck", "к"),
    ("qu", "кв"),
    ("oo", "у"),
    ("ee", "и"),
    ("ea", "и"),
    ("ou", "ау"),
    ("ai", "эй"),
    ("ay", "эй"),
    ("ts", "ц"),
    ("ya", "я"),
    ("yu", "ю"),
    ("yo", "ё"),
    ("x", "кс"),
    ("j", "дж"),
)
"""Сочетания букв — раньше отдельных букв."""
_SINGLE_LETTERS = str.maketrans("abcdefghiklmnopqrstuvwyz", "абкдефгхиклмнопкрстуввиз")
_SOFT_C_PATTERN = re.compile(r"c(?=[eiy])")
_LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'\u2019][A-Za-z0-9]+)*")
_LATIN_PARTS_PATTERN = re.compile(r"[A-Za-z]+|\d+")
_CYRILLIC_CAPS_PATTERN = re.compile(r"\b[А-ЯЁ]{2,}\b")


def spell_letters(letters: str, names: Mapping[str, str]) -> str:
    """«тэз+э», «сиар+эм»: названия букв слитно, ударение на последней, как в речи.

    Слитно, а не через дефис: «тэ-з+э» Silero читает как «тэлзэ» — так показал замер
    озвучка → Whisper (`scripts/voice_roundtrip.py`), а слитное распознаётся как «ТЗ».
    """
    spoken = [names[letter].replace(STRESS_MARK, "") for letter in letters[:-1]]
    return "".join([*spoken, names[letters[-1]]])


def transliterate(word: str) -> str:
    """Латинское слово по-русски: по словарю («Notion» → «ноушн») или по буквам («Asana»)."""
    lowered = word.lower()
    known = LATIN_WORDS.get(lowered)
    if known is not None:
        return known
    text = _SOFT_C_PATTERN.sub("s", lowered)
    for latin, cyrillic in _TRANSLITERATION:
        text = text.replace(latin, cyrillic)
    return text.translate(_SINGLE_LETTERS)


def read_latin(text: str) -> str:
    """Все латинские слова — кириллицей: «CRM» → «сиар+эм», «Q3» → «кь+ю три»."""
    return _LATIN_TOKEN_PATTERN.sub(lambda match: _latin_token_words(match[0]), text)


def spell_abbreviations(text: str) -> str:
    """Аббревиатуры кириллицей — по буквам: «ТЗ» → «тэз+э»; «ВУЗ» и «СРОЧНО» — словом."""
    return _CYRILLIC_CAPS_PATTERN.sub(lambda match: _caps_word(match[0]), text)


def _latin_token_words(token: str) -> str:
    known = LATIN_WORDS.get(token.lower())
    if known is not None:
        return known
    return " ".join(_latin_part_words(part) for part in _LATIN_PARTS_PATTERN.findall(token))


def _latin_part_words(part: str) -> str:
    if part.isdigit():
        return cardinal(int(part))
    if part.isupper() and len(part) <= MAX_SPELLED_LATIN_LETTERS:
        return spell_letters(part, LATIN_LETTER_NAMES)
    return transliterate(part)


def _caps_word(word: str) -> str:
    spelled = (
        word not in WORD_ACRONYMS
        and len(word) <= MAX_SPELLED_LETTERS
        and all(letter in CYRILLIC_LETTER_NAMES for letter in word)
    )
    return spell_letters(word, CYRILLIC_LETTER_NAMES) if spelled else word.lower()
