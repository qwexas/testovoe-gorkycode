"""Ссылка на изменяемую запись — по словам пользователя, а не по списку записей в фокусе.

GigaChat-2-Pro на «Отметь звонок Ивану как сделанный», когда в фокусе была «Встреча
с Иваном», 4 раза из 4 подставлял в описание её название, тип «встреча» и придуманную
дату. Нужная запись — напоминание «Позвонить Ивану» — в фокусе не было, и бизнес-логика
искала бы не то. Поэтому код сверяет ответ модели с самой репликой:

- описание записи (`query`) должно состоять из слов реплики: если больше половины его лемм
  в реплике нет, описанием становятся слова самой реплики без команд и указаний времени;
- день записи (`target.when`) остаётся, только если в реплике есть слово о дне или времени;
- тип записи (`target.event_type`) остаётся, только если в реплике назван тип.
"""

import re
from functools import cache

from app.search.lemmas import (
    DEFAULT_STOP_WORDS,
    MorphLemmatizer,
    normalize_yo,
    shared_morph_analyzer,
)

MIN_QUERY_COVERAGE = 0.5
"""Доля лемм описания, которая должна быть в реплике: больше половины, а у описания из двух
слов — оба. «Встреча с Иваном» для «Отметь звонок Ивану» — только одно слово из двух."""

CHANGE_COMMAND_WORDS = frozenset(
    {
        "отметить", "отмечать", "пометить", "перенести", "переносить", "сдвинуть", "сдвигать",
        "передвинуть", "передвигать", "удалить", "удалять", "удали", "удаль", "убрать",
        "убирать", "отменить", "отменять", "переименовать", "переименовывать", "назвать",
        "выполнить", "выполнять", "сделанный", "готовый",
        "лучше", "тогда", "давать", "ладно", "нет",
    }
)  # fmt: skip
"""Слова-команды изменения и связки разговора («нет, лучше перенеси…», «тогда сдвинь…»):
в описании записи их не бывает. «удали» pymorphy3 разбирает как «удаль», поэтому в списке и
форма, и ошибочная лемма."""

PREPOSITION = "PREP"

_TOKEN = re.compile(r"[а-яёa-z0-9]+(?:-[а-яё]+)*", re.IGNORECASE)
_MOMENT_WORD = re.compile(
    r"\d|\b(?:сегодн|завтр|послезавтр|вчер|позавчер|понедельник|вторник|сред[аеуы]\b|четверг"
    r"|пятниц|суббот|воскресень|недел|выходн|месяц|январ|феврал|марта?\b|апрел|ма[йяю]\b"
    r"|июн|июл|август|сентябр|октябр|ноябр|декабр|утр|вечер|дн[её]м\b|ноч|обед|полд|полноч"
    r"|через)",
    re.IGNORECASE,
)
"""День или время в реплике: «завтрашний», «в пятницу», «26 ноября», «в 15:00», «утром»."""
OBJECT_PRONOUNS = frozenset({"её", "ее", "его", "неё", "нее", "него", "ней", "нём", "нем"})
"""«Перенеси её», «удали его». Перед существительным это притяжательное: «его команда»."""
DEMONSTRATIVES = frozenset({"эту", "этот", "эта", "этой", "этого", "это"})
"""«Удали эту встречу», «отметь это»."""
LAST_REFERENCES = frozenset(
    {"последнюю", "последний", "последнее", "последняя", "последней", "последнего"}
)
"""«Отметь последнюю выполненной»; внутри описания «проверить последний отчёт» — не ссылка."""
POSSESSED_PARTS_OF_SPEECH = frozenset({"NOUN", "ADJF"})
REFERENCE_INTERVAL_WORDS = frozenset(
    {"день", "сутки", "час", "часик", "минута", "минутка", "полчаса", "полчасик"}
)
_EVENT_TYPE_WORD = re.compile(
    r"\b(?:встреч|созвон|совещан|планёрк|планерк|переговор|митинг|задач|напомина|напомн)",
    re.IGNORECASE,
)
"""Тип записи в реплике. «Звонок» не тип: «Позвонить Ивану» — задача или напоминание,
«Созвон с Иваном» — встреча."""


def user_description(model_query: str | None, text: str) -> str | None:
    """Описание записи словами реплики.

    Описание модели остаётся, если больше половины его лемм есть в реплике. Иначе — слова
    самой реплики без команд, местоимений и указаний дня; `None`, если таких слов нет
    («отметь её выполненной»).
    """
    if model_query is None:
        return _content_words(text)
    query_lemmas = set(_lemmatizer().lemmas(model_query))
    if not query_lemmas:
        return model_query
    covered = len(query_lemmas.intersection(_lemmatizer().lemmas(text))) / len(query_lemmas)
    if covered > MIN_QUERY_COVERAGE:
        return model_query
    return _content_words(text)


def spoken_in(phrase: str, text: str) -> bool:
    """Сказана ли фраза модели в реплике: больше половины её лемм есть в `text`.

    Так проверяются остальные команды (`rest`), которые модель выписала из реплики.
    """
    phrase_lemmas = set(_lemmatizer().lemmas(phrase))
    if not phrase_lemmas:
        return False
    covered = len(phrase_lemmas.intersection(_lemmatizer().lemmas(text))) / len(phrase_lemmas)
    return covered > MIN_QUERY_COVERAGE


def same_record(description: str, title: str) -> bool:
    """Описание называет запись: «встречу с Иваном» и «Встреча с Иваном» — одна запись."""
    description_lemmas = set(_lemmatizer().lemmas(description))
    return bool(description_lemmas) and description_lemmas == set(_lemmatizer().lemmas(title))


def names_record_by_pronoun(text: str, *, new_title: str | None = None) -> bool:
    """Названа ли запись местоимением — тогда это запись из контекста диалога.

    Модель иногда «разворачивает» местоимение в название записи из фокуса, а описание
    словами реплики дало бы мусор: «нет, лучше перенеси её…» → «лучше».
    После «эту задачу» может быть явное описание — оно важнее ссылки на контекст.
    Новое название при переименовании не описывает выбираемую запись.
    """
    tokens = [token.lower() for token in _TOKEN.findall(text)]
    for index, token in enumerate(tokens):
        if (
            token not in DEMONSTRATIVES
            and token not in OBJECT_PRONOUNS
            and token not in LAST_REFERENCES
        ):
            continue
        # Внутри названия («проверить этот отчёт», «позвонить ей») это не ссылка на запись.
        if any(_is_content(word) for word in tokens[:index]):
            continue
        if token in LAST_REFERENCES:
            # Самостоятельное описание после «последний» тоже важнее фокуса.
            return not any(
                _is_content(word) and not names_event_type(word) for word in tokens[index + 1 :]
            )
        if token in DEMONSTRATIVES and (index == 0 or not _is_preposition(tokens[index - 1])):
            return not _has_record_description(tokens[index + 1 :], new_title)
        if token in OBJECT_PRONOUNS and not _starts_noun_phrase(tokens[index + 1 : index + 2]):
            return True
    return False


def _has_record_description(tokens: list[str], new_title: str | None) -> bool:
    """Содержание после «эту», кроме типа, времени и нового названия при rename."""
    title_tokens = _TOKEN.findall(new_title.lower()) if new_title else []
    if title_tokens and normalize_yo(" ".join(tokens[-len(title_tokens) :])) == normalize_yo(
        " ".join(title_tokens)
    ):
        tokens = tokens[: -len(title_tokens)]
    temporal = _temporal_indices(tokens)
    # «На час / на полчаса» и «в десять тридцать» дополняют ссылку временем,
    # а не называют другую запись. Числительные с единицами уже учтены выше.
    for index, word in enumerate(tokens):
        if (
            index > 0
            and tokens[index - 1] in {"на", "через"}
            and REFERENCE_INTERVAL_WORDS.intersection(_lemmatizer().lemmas(word))
        ):
            temporal.add(index)
    return any(
        index not in temporal
        and _is_content(word)
        and not names_event_type(word)
        and not _time_modifier(word)
        for index, word in enumerate(tokens)
    )


def names_moment(text: str) -> bool:
    """Есть ли в реплике день или время."""
    return _MOMENT_WORD.search(text) is not None


def names_event_type(text: str) -> bool:
    """Назван ли в реплике тип записи: встреча, задача, напоминание."""
    return _EVENT_TYPE_WORD.search(text) is not None


def _content_words(text: str) -> str | None:
    """Слова реплики от первого значимого до последнего: «звонок Ивану» из «Отметь звонок
    Ивану как сделанный». Предлоги между значимыми словами остаются: «встречу с Иваном»."""
    tokens = _TOKEN.findall(text)
    temporal = _temporal_indices(tokens)
    content = [
        index for index, token in enumerate(tokens) if index not in temporal and _is_content(token)
    ]
    if not content:
        return None
    return " ".join(
        token
        for index, token in enumerate(tokens)
        if content[0] <= index <= content[-1]
        and index not in temporal
        and (_is_content(token) or _is_preposition(token))
    )


def _temporal_indices(tokens: list[str]) -> set[int]:
    """«Следующую» в «на следующую неделю», числительные в «через два дня» — часть даты."""
    temporal: set[int] = set()
    for index, token in enumerate(tokens):
        unit = bool(set(_lemmatizer().lemmas(token)) & {"день", "сутки", "час", "минута"})
        if not names_moment(token) and not (
            unit
            and index > 0
            and (tokens[index - 1].lower() == "через" or _time_modifier(tokens[index - 1]))
        ):
            continue
        temporal.add(index)
        previous = index - 1
        while previous >= 0 and _time_modifier(tokens[previous]):
            temporal.add(previous)
            previous -= 1
    return temporal


def _time_modifier(token: str) -> bool:
    parsed = shared_morph_analyzer().parse(token.lower())[0]
    return (
        parsed.tag.POS == "NUMR"
        or "Anum" in parsed.tag
        or parsed.normal_form
        in {
            "следующий",
            "прошлый",
            "этот",
            "текущий",
            "ближайший",
            "предстоящий",
        }
    )


def _is_content(token: str) -> bool:
    return bool(_lemmatizer().lemmas(token)) and not names_moment(token)


def _starts_noun_phrase(following: list[str]) -> bool:
    if not following:
        return False
    return shared_morph_analyzer().parse(following[0])[0].tag.POS in POSSESSED_PARTS_OF_SPEECH


def _is_preposition(token: str) -> bool:
    return bool(shared_morph_analyzer().parse(token.lower())[0].tag.POS == PREPOSITION)


@cache
def _lemmatizer() -> MorphLemmatizer:
    return MorphLemmatizer(DEFAULT_STOP_WORDS | CHANGE_COMMAND_WORDS)
