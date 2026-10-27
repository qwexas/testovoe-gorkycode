"""Сверка действия и названия со словами-командами реплики.

Две детерминированные страховки поверх ответа модели:

1. **Создание, а не перенос.** «Поставь встречу с Иваном на следующей неделе», когда
   «Встреча с Иваном» уже есть, GigaChat-2-Pro в 2 из 3 прогонов разбирал как перенос
   существующей встречи. Если в реплике есть глагол создания («поставь», «добавь», «создай»,
   «запланируй», «назначь», «напомни», «запиши», «нужно», «надо») и нет глагола переноса или
   изменения («перенеси», «сдвинь», «передвинь», «перемести», «измени», «отложи», «поменяй»),
   это создание. Описание записи, которое модель положила в `query`, становится названием.
   Местоимение («поставь её на пятницу») — ссылка на запись, такая реплика не трогается.
2. **Название-заглушка.** «Поставь встречу на завтра в 12» — модель называет запись
   «Встреча». Это не название, а тип: название пустое, и бизнес-логика спросит «Как назвать
   встречу?». Заглушками считаются названия типов и общие слова — «встреча», «задача»,
   «напоминание», «дело», «событие», «запись», «мероприятие», в том числе с «новый».
   «Созвон», «планёрка», «совещание» — уже содержание (формат встречи), их оставляем.
"""

import re

from app.nlu.expressions import DateKind
from app.nlu.grounding import names_record_by_pronoun
from app.nlu.interfaces import Action
from app.nlu.schema import Extraction
from app.search.lemmas import normalize_yo, shared_morph_analyzer

CREATE_VERBS = frozenset(
    {
        "поставить", "ставить", "добавить", "добавлять", "создать", "создавать",
        "запланировать", "планировать", "назначить", "назначать", "напомнить", "напоминать",
        "записать", "записывать", "внести", "вносить", "завести", "заводить",
    }
)  # fmt: skip
CREATE_WORDS = frozenset({"нужно", "надо"})
"""«На следующей неделе нужно встретиться с Иваном» — тоже создание."""
CHANGE_VERBS = frozenset(
    {
        "перенести", "переносить", "сдвинуть", "сдвигать", "передвинуть", "передвигать",
        "подвинуть", "двигать", "переместить", "перемещать", "изменить", "изменять",
        "отложить", "откладывать", "поменять", "менять", "перекинуть", "перебросить",
        "перепланировать",
    }
)  # fmt: skip
GENERIC_TITLE_WORDS = frozenset(
    {"встреча", "задача", "напоминание", "дело", "событие", "запись", "мероприятие", "новый"}
)
"""Слова, из которых не складывается название: тип записи и общие слова."""

_WORD = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def creation_over_change(extraction: Extraction, text: str) -> Extraction:
    """Перенос с глаголом создания и без глагола переноса — создание (см. модуль)."""
    if extraction.action is not Action.RESCHEDULE or extraction.about_last:
        return extraction
    if names_record_by_pronoun(text) or not asks_to_create(text) or asks_to_change(text):
        return extraction
    return extraction.model_copy(
        update={
            "action": Action.CREATE,
            "title": extraction.title or extraction.query,
            "query": "",
            "target_date": DateKind.NONE,
        }
    )


def asks_to_create(text: str) -> bool:
    """Есть ли в реплике глагол создания или «нужно» / «надо»."""
    words = _words(text)
    return not CREATE_WORDS.isdisjoint(words) or not CREATE_VERBS.isdisjoint(_lemmas(words))


def asks_to_change(text: str) -> bool:
    """Есть ли в реплике глагол переноса или изменения."""
    return not CHANGE_VERBS.isdisjoint(_lemmas(_words(text)))


def is_generic_title(title: str) -> bool:
    """«Встреча», «Новая задача» — не название, а тип записи."""
    words = _words(title)
    return bool(words) and set(_lemmas(words)) <= GENERIC_TITLE_WORDS


def _words(text: str) -> list[str]:
    return [normalize_yo(word.lower()) for word in _WORD.findall(text)]


def _lemmas(words: list[str]) -> list[str]:
    analyzer = shared_morph_analyzer()
    return [normalize_yo(str(analyzer.parse(word)[0].normal_form)) for word in words]
