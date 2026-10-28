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
3. **Несколько команд.** «Перенеси планёрку на 11 и удали встречу с Петром»: `Intent`
   описывает одну команду, и модель не всегда выписывает остальные в `rest`. Если в реплике
   два повелительных глагола-команды («перенеси», «удали», «создай»…) и между ними есть
   слова, всё со второго глагола — остальные команды (`other_commands`). Инфинитив —
   содержание записи, а не команда: «поставь задачу добавить отчёт» — одна команда.
   Повелительный глагол в названии записи — тоже содержание: в кавычках («создай задачу
   «удали старые файлы»»), после двоеточия («поставь задачу: найди подрядчика») или
   в названии, которое выделила модель.
"""

import itertools
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
OTHER_COMMAND_VERBS = frozenset(
    {
        "удалить", "убрать", "отменить", "отметить", "переименовать", "найти", "показать",
    }
)  # fmt: skip
"""Команды-глаголы, кроме создания и переноса: вместе с ними — признак отдельной команды."""
COMMAND_VERBS = CREATE_VERBS | CHANGE_VERBS | OTHER_COMMAND_VERBS
IMPERATIVE = "impr"
GENERIC_TITLE_WORDS = frozenset(
    {"встреча", "задача", "напоминание", "дело", "событие", "запись", "мероприятие", "новый"}
)
"""Слова, из которых не складывается название: тип записи и общие слова."""

MAX_FRONTED_WORDS = 3
"""Сколько слов между запятой и глаголом считать его дополнением: «, а созвон перенеси».
Длиннее — это перечисление внутри первой команды: «с Иваном, Петром на 17 и удали…»."""
LINKING_WORDS = frozenset({"и", "а", "ещё", "еще", "потом", "затем", "также", "плюс"})
"""Связки между командами: «…, а потом удали Y» — остальное начинается с «удали»."""
TRAILING_PUNCTUATION = " \t\n.,!?;:«»\"'"
RECORD_PREFIX_WORDS = 2
"""Сколько первых слов команды сверять с названием записи: «найди подрядчика» — название
«Найти подрядчика», а «удали встречу» при названии «Удали старые файлы» — команда."""
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
            "target_time": "",
        }
    )


def asks_to_create(text: str) -> bool:
    """Есть ли в реплике глагол создания или «нужно» / «надо»."""
    words = _words(text)
    return not CREATE_WORDS.isdisjoint(words) or not CREATE_VERBS.isdisjoint(_lemmas(words))


def asks_to_change(text: str) -> bool:
    """Есть ли в реплике глагол переноса или изменения."""
    return not CHANGE_VERBS.isdisjoint(_lemmas(_words(text)))


def other_commands(text: str, record: str = "") -> str | None:
    """Вторая и следующие команды реплики словами пользователя; `None` — команда одна.

    «Перенеси планёрку на 11 и удали встречу с Петром» → «удали встречу с Петром».
    Дополнение перед глаголом остаётся с ним, если команды разделены запятой: «удали
    встречу с Петром, а созвон перенеси на завтра» → «созвон перенеси на завтра».
    Глаголы подряд («нет, отмени, перенеси её») — одна команда: у первой нет содержания.
    `record` — название или описание записи первой команды: глагол из него — не команда.
    """
    record_forms = frozenset().union(*(_normal_forms(word) for word in _words(record)))
    commands = [
        match
        for match in _WORD.finditer(text)
        if _is_command(match.group()) and not _quoted(text, match.start())
    ]
    for first, second in itertools.pairwise(commands):
        between = text[first.end() : second.start()]
        if _WORD.search(between) is None or between.rstrip().endswith(":"):
            continue
        start = text.rfind(",", first.end(), second.start()) + 1
        fronted = _WORD.findall(text, start, second.start())
        if not start or len(fronted) > MAX_FRONTED_WORDS:
            start = second.start()
        words = text[start:].split()
        while words and words[0].lower() in LINKING_WORDS:
            words.pop(0)
        rest = " ".join(words).strip(TRAILING_PUNCTUATION)
        if rest and not _names_record(rest, record_forms):
            return rest
    return None


def is_generic_title(title: str) -> bool:
    """«Встреча», «Новая задача» — не название, а тип записи."""
    words = _words(title)
    return bool(words) and set(_lemmas(words)) <= GENERIC_TITLE_WORDS


def _words(text: str) -> list[str]:
    return [normalize_yo(word.lower()) for word in _WORD.findall(text)]


def _is_command(word: str) -> bool:
    """Повелительная форма глагола-команды: «перенеси», «удали», «создай»."""
    return any(
        parse.tag.mood == IMPERATIVE and normalize_yo(str(parse.normal_form)) in COMMAND_VERBS
        for parse in shared_morph_analyzer().parse(word.lower())
    )


def _quoted(text: str, position: int) -> bool:
    """Стоит ли `position` внутри кавычек: «…» или "…"."""
    opened = text.count("«", 0, position) > text.count("»", 0, position)
    return opened or text.count('"', 0, position) % 2 == 1


def _names_record(rest: str, record_forms: frozenset[str]) -> bool:
    """Начало «команды» совпадает с названием записи: это её содержание, а не команда.

    Сверяются все разборы слова: первый разбор «удали» — не «удалить».
    """
    words = _words(rest)[:RECORD_PREFIX_WORDS]
    return bool(record_forms) and all(_normal_forms(word) & record_forms for word in words)


def _normal_forms(word: str) -> frozenset[str]:
    return frozenset(
        normalize_yo(str(parse.normal_form)) for parse in shared_morph_analyzer().parse(word)
    )


def _lemmas(words: list[str]) -> list[str]:
    analyzer = shared_morph_analyzer()
    return [normalize_yo(str(analyzer.parse(word)[0].normal_form)) for word in words]
