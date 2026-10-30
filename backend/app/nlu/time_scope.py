"""время поиска по словам самой реплики: «была» — прошлое, «будет» — будущее.

Модель иногда теряет `time_scope` в длинном контексте диалога: «Когда у меня будет созвон
с Орбитой?» посреди разговора она разобрала как `any`, хотя без контекста — как `future`.
Явные маркеры времени в тексте — детерминированная страховка: если они однозначно указывают
на прошлое или будущее, это и есть ответ. Если маркеров нет или они противоречат друг другу
(«когда будет встреча, которую мы перенесли»), остаётся ответ модели.

Маркеры:
- глагол в прошедшем времени: «была», «ставил», «звонил», «обсуждали»;
- глагол в будущем времени, кроме 2-го лица: «будет», «позвоню», «встретимся». 2-е лицо —
  вежливая просьба к ассистенту («найдёшь», «подскажешь»), а не время события;
- слова: прошлое — «прошлый раз», «последний», «предыдущий», «когда-то», «раньше», «давно»;
  будущее — «следующий», «ближайший», «предстоящий», «запланированный», «скоро».

«На прошлой неделе», «в следующем месяце», «в ближайшую пятницу» — не маркеры: это период,
его модель кладёт в `date`, и хранилище фильтрует по нему. Причастия («запланированы») по
грамматике тоже прошедшего времени, поэтому считаются только глаголы в личной форме.
"""

import re
from collections.abc import Sequence

from app.nlu.interfaces import TimeScope
from app.search.lemmas import normalize_yo, shared_morph_analyzer

_WORD = re.compile(r"[а-яё]+(?:-[а-яё]+)*")

PAST_STEMS = ("прошл", "последн", "предыдущ")
PAST_WORDS = frozenset({"когда-то", "раньше", "ранее", "давно", "недавно", "однажды"})
FUTURE_STEMS = ("следующ", "ближайш", "предстоящ", "грядущ", "запланирован", "намечен")
FUTURE_WORDS = frozenset({"скоро", "впереди"})
PERIOD_STEMS = (
    "недел",
    "месяц",
    "год",
    "выходн",
    "квартал",
    "понедельник",
    "вторник",
    "сред",
    "четверг",
    "пятниц",
    "суббот",
    "воскресень",
)
"""слово после «прошлой», «следующей», «ближайшей», которое делает их периодом."""

VERB = "VERB"
PAST_TENSE = "past"
FUTURE_TENSE = "futr"
SECOND_PERSON = "2per"


def search_time_scope(model_scope: TimeScope, text: str) -> TimeScope:
    """время поиска: по маркерам в тексте, если они однозначны, иначе — ответ модели."""
    return time_scope_in_text(text) or model_scope


def time_scope_in_text(text: str) -> TimeScope | None:
    """прошлое или будущее по маркерам в реплике; `None` — маркеров нет или они спорят."""
    words = _WORD.findall(normalize_yo(text.lower()))
    found = {
        scope
        for position, word in enumerate(words)
        if (scope := _word_scope(word, words[position + 1 : position + 2])) is not None
    }
    return found.pop() if len(found) == 1 else None


def _word_scope(word: str, following: Sequence[str]) -> TimeScope | None:
    if word in PAST_WORDS:
        return TimeScope.PAST
    if word in FUTURE_WORDS:
        return TimeScope.FUTURE
    if word.startswith(PAST_STEMS + FUTURE_STEMS):
        if _starts_period(following):
            return None
        return TimeScope.PAST if word.startswith(PAST_STEMS) else TimeScope.FUTURE
    return _verb_tense(word)


def _starts_period(following: Sequence[str]) -> bool:
    return bool(following) and following[0].startswith(PERIOD_STEMS)


def _verb_tense(word: str) -> TimeScope | None:
    tag = shared_morph_analyzer().parse(word)[0].tag
    if tag.POS != VERB:
        return None
    if PAST_TENSE in tag:
        return TimeScope.PAST
    if FUTURE_TENSE in tag and SECOND_PERSON not in tag:
        return TimeScope.FUTURE
    return None
