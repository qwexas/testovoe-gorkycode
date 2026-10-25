"""Лемматизация русского текста для поиска: pymorphy3, стоп-слова, имена людей.

Леммы нужны лексической половине гибридного поиска: «Иваном» и «Ивану» должны
совпасть с «иван», «договору» — с «договор». Служебные слова и слова-команды
ассистенту («найди», «задачу», «когда», «у меня») из лемм убираются: они есть
почти в каждом запросе, но ничего не говорят о том, какую запись ищут.
"""

import re
import threading
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache

import pymorphy3  # type: ignore[import-untyped]
from pymorphy3.analyzer import Parse  # type: ignore[import-untyped]

_TOKEN = re.compile(r"[а-яёa-z0-9]+")
_CYRILLIC_WORD = re.compile(r"[а-яё]+")

SERVICE_PARTS_OF_SPEECH = frozenset({"PREP", "CONJ", "PRCL", "INTJ", "NPRO", "PRED"})
"""Предлоги, союзы, частицы, междометия, местоимения-существительные, «нужно/надо»."""

PRONOUN_ADJECTIVE_GRAMMEME = "Apro"
"""Местоимения-прилагательные: «мой», «этот», «какой», «весь», «свой»."""

PERSON_NAME_GRAMMEMES = frozenset({"Name", "Surn", "Patr"})
UNKNOWN_WORD_PREFERRED_POS = "NOUN"
AMBIGUOUS_LEMMA_MIN_SCORE = 0.25
"""Омонимия: лемма остаётся, если на неё приходится не меньше четверти вероятности разбора."""

LEMMA_CACHE_SIZE = 50_000

ASSISTANT_WORDS = frozenset({"горький", "ассистент", "пожалуйста", "спасибо", "привет"})
RECORD_KIND_WORDS = frozenset(
    {"задача", "задачка", "напоминание", "событие", "запись", "дело", "список"}
)
COMMAND_VERBS = frozenset(
    {
        "найти", "находить", "искать", "поискать", "отыскать", "разыскать",
        "показать", "показывать", "подсказать", "сказать", "посмотреть", "глянуть",
        "вспомнить", "помнить", "ставить", "поставить", "создать", "создавать",
        "добавить", "добавлять", "запланировать", "планировать", "делать", "сделать",
        "быть", "есть", "иметься", "мочь", "хотеть", "знать", "казаться",
    }
)  # fmt: skip
QUESTION_AND_TIME_WORDS = frozenset(
    {
        "когда", "где", "куда", "откуда", "как", "сколько", "почему", "зачем",
        "нибудь", "либо", "там", "тут", "здесь", "вообще", "именно", "вроде",
        "давно", "недавно", "раньше", "ранее", "уже", "еще", "тоже", "также",
        "вчера", "сегодня", "завтра", "позавчера", "послезавтра",
        "прошлый", "неделя", "месяц", "год",
    }
)  # fmt: skip

DEFAULT_STOP_WORDS = ASSISTANT_WORDS | RECORD_KIND_WORDS | COMMAND_VERBS | QUESTION_AND_TIME_WORDS
"""Стоп-слова сверх служебных частей речи (их отсекает разбор pymorphy3).

- `ASSISTANT_WORDS` — обращение к ассистенту и вежливость: «Горький, найди, пожалуйста…».
- `RECORD_KIND_WORDS` — названия видов записей: «найди задачу про…» ищет не слово «задача».
  Тип записи — отдельное поле, его фильтрует хранилище. «Встреча» сюда не входит:
  в названиях записей это содержательное слово («Встреча с Иваном по CRM»).
- `COMMAND_VERBS` — глаголы-команды и связки запроса: «найди», «покажи», «я ставил»,
  «у меня была». Глаголы действий из самих записей («позвонить», «отправить»,
  «проверить», «напомнить») сохраняются.
- `QUESTION_AND_TIME_WORDS` — вопросительные слова и указания времени. Период поиска
  разбирает LLM и фильтрует хранилище, а в тексте записи этих слов нет.
"""

ABBREVIATIONS: Mapping[str, tuple[str, ...]] = {
    "тз": ("технический", "задание"),
    "кп": ("коммерческий", "предложение"),
}
"""Деловые сокращения, которые в записях встречаются и полностью, и сокращённо.

Раскрываются и в запросах, и в записях, поэтому «ТЗ» совпадает с «техническим заданием»
в обе стороны. Только однозначные: «ПО» совпало бы с предлогом, «ДР» — с «и др.».
"""


def normalize_yo(word: str) -> str:
    """«Отчёт» и «отчет» — одно слово: пользователи и распознавание речи пишут по-разному."""
    return word.replace("ё", "е")


_analyzer: pymorphy3.MorphAnalyzer | None = None
_analyzer_lock = threading.Lock()


def shared_morph_analyzer() -> pymorphy3.MorphAnalyzer:
    """Единственный на процесс `MorphAnalyzer`: словари грузятся один раз.

    После загрузки анализатор только читает словари, поэтому его можно звать из разных потоков.
    """
    global _analyzer
    with _analyzer_lock:
        if _analyzer is None:
            _analyzer = pymorphy3.MorphAnalyzer()
        return _analyzer


class MorphLemmatizer:
    """Леммы для поиска: «Встреча с Иваном» → `["встреча", "иван"]`.

    Разборы слов кэшируются (`lru_cache` потокобезопасен), числа и латиница
    («CRM», «2024») сохраняются как есть в нижнем регистре.
    """

    def __init__(self, stop_words: frozenset[str] = DEFAULT_STOP_WORDS) -> None:
        self._morph = shared_morph_analyzer()
        self._stop_words = stop_words
        self._word_lemmas = lru_cache(maxsize=LEMMA_CACHE_SIZE)(self._analyze_word)
        self._person_name = lru_cache(maxsize=LEMMA_CACHE_SIZE)(self._detect_person_name)

    def lemmas(self, text: str) -> list[str]:
        """Уникальные значимые леммы текста в порядке появления, без стоп-слов."""
        unique: dict[str, None] = {}
        for token in _TOKEN.findall(text.lower()):
            unique.update(dict.fromkeys(self._word_lemmas(token)))
        return list(unique)

    def is_proper_noun(self, lemma: str) -> bool:
        """Имя, фамилия или отчество человека: «иван» — да, «вектор» и «хакатон» — нет."""
        return self._person_name(lemma)

    def _analyze_word(self, word: str) -> tuple[str, ...]:
        if word in self._stop_words:
            return ()
        if word in ABBREVIATIONS:
            return ABBREVIATIONS[word]
        if not _CYRILLIC_WORD.fullmatch(word):
            return (word,)
        parses = self._morph.parse(word)
        if _is_service_word(parses[0]):
            return ()
        if self._morph.word_is_known(word):
            candidates = _likely_lemmas(parses)
        else:
            candidates = [_guess_unknown_word_lemma(word, parses)]
        lemmas = dict.fromkeys(normalize_yo(lemma) for lemma in candidates)
        return tuple(lemma for lemma in lemmas if lemma not in self._stop_words)

    def _detect_person_name(self, lemma: str) -> bool:
        if not _CYRILLIC_WORD.fullmatch(lemma) or not self._morph.word_is_known(lemma):
            return False
        grammemes = self._morph.parse(lemma)[0].tag.grammemes
        return not PERSON_NAME_GRAMMEMES.isdisjoint(grammemes)


def _is_service_word(parse: Parse) -> bool:
    tag = parse.tag
    return tag.POS in SERVICE_PARTS_OF_SPEECH or PRONOUN_ADJECTIVE_GRAMMEME in tag.grammemes


def _likely_lemmas(parses: Sequence[Parse]) -> list[str]:
    """Все правдоподобные леммы той же части речи, что и лучший разбор.

    «аналитике» — и «аналитика», и «аналитик»; если оставить одну, запрос в другой
    форме («аналитика») не совпадёт с записью. Сумма вероятностей по лемме отсекает
    редкие варианты вроде «встречу» → «встретить».
    """
    best_pos = parses[0].tag.POS
    score_by_lemma: defaultdict[str, float] = defaultdict(float)
    for parse in parses:
        if best_pos == parse.tag.POS:
            score_by_lemma[parse.normal_form] += parse.score
    best_lemma = parses[0].normal_form
    return [
        lemma
        for lemma, score in score_by_lemma.items()
        if lemma == best_lemma or score >= AMBIGUOUS_LEMMA_MIN_SCORE
    ]


def _guess_unknown_word_lemma(word: str, parses: Iterable[Parse]) -> str:
    """Лемма слова, которого нет в словаре: «хакатону» → «хакатон», «демо» → «демо».

    Незнакомые слова в задачах — почти всегда существительные (жаргон, названия),
    а угаданный по окончанию глагол или причастие чаще ошибочен («демо» → «дть»).
    """
    for parse in parses:
        if parse.tag.POS == UNKNOWN_WORD_PREFERRED_POS:
            return str(parse.normal_form)
    return word
