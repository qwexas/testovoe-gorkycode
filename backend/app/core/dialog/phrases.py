"""Тексты ответов Горького (решение Q24): шаблоны в коде, LLM ответы не пишет.

Все формулировки диалога — здесь: по-русски, человеческим языком, без эмодзи.
Даты — относительно сегодняшнего дня по Москве: «сегодня, 27 октября, в 15:00»,
«завтра», «в пятницу, 30 октября»; дальше недели — «12 ноября», прошлые и другого
года — с годом: «5 марта 2026 в 15:45».
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from operator import itemgetter
from types import MappingProxyType
from typing import Final

from app.core.enums import EventStatus, EventType, PendingExpectation
from app.core.events import EventCard
from app.core.schedule import DEFAULT_MEETING_DURATION
from app.nlu.interfaces import Action, Period

# --- Грамматика ----------------------------------------------------------------------------


class Gender(Enum):
    """Род существительного — от него зависят «одна/одно», «последняя/последнее»."""

    FEMININE = "feminine"
    NEUTER = "neuter"


@dataclass(frozen=True, slots=True)
class Noun:
    """Существительное в нужных ответам формах."""

    nominative: str
    accusative: str
    counted: tuple[str, str, str]
    """Формы после числа: 1 задача, 2 задачи, 5 задач."""
    gender: Gender

    @property
    def genitive_plural(self) -> str:
        """«Встреч нет», «задач нет»."""
        return self.counted[2]


TYPE_NOUNS: Final[Mapping[EventType, Noun]] = MappingProxyType(
    {
        EventType.TASK: Noun("задача", "задачу", ("задача", "задачи", "задач"), Gender.FEMININE),
        EventType.REMINDER: Noun(
            "напоминание",
            "напоминание",
            ("напоминание", "напоминания", "напоминаний"),
            Gender.NEUTER,
        ),
        EventType.MEETING: Noun(
            "встреча", "встречу", ("встреча", "встречи", "встреч"), Gender.FEMININE
        ),
    }
)
THING = Noun("дело", "дело", ("дело", "дела", "дел"), Gender.NEUTER)
ENTRY = Noun("запись", "запись", ("запись", "записи", "записей"), Gender.FEMININE)

_ONE = MappingProxyType({Gender.FEMININE: "одна", Gender.NEUTER: "одно"})
_NEAREST = MappingProxyType({Gender.FEMININE: "ближайшая", Gender.NEUTER: "ближайшее"})
_LATEST = MappingProxyType({Gender.FEMININE: "последняя", Gender.NEUTER: "последнее"})
_WAS = MappingProxyType({Gender.FEMININE: "была", Gender.NEUTER: "было"})
_WHICH = MappingProxyType({Gender.FEMININE: "какую", Gender.NEUTER: "какое"})
_DONE = MappingProxyType({Gender.FEMININE: "сделанной", Gender.NEUTER: "сделанным"})
_SUCH = MappingProxyType({Gender.FEMININE: "такая", Gender.NEUTER: "такое"})
_ONE_MORE = MappingProxyType({Gender.FEMININE: "ещё одну", Gender.NEUTER: "ещё одно"})

EN_DASH = "\u2013"
"""Короткое тире в диапазоне времени встречи: «15:00» + тире + «16:00»."""

TYPE_ORDER = (EventType.MEETING, EventType.TASK, EventType.REMINDER)
"""Порядок типов в сводке: «2 встречи и задача»."""


def plural(count: int, forms: tuple[str, str, str]) -> str:
    """Форма слова после числа: 1 и 21 — первая, от 2 до 4 и от 22 до 24 — вторая, иначе третья."""
    last_two = abs(count) % 100
    last = last_two % 10
    if 11 <= last_two <= 14 or last == 0 or last >= 5:
        return forms[2]
    return forms[0] if last == 1 else forms[1]


def count_phrase(count: int, noun: Noun) -> str:
    """«одна встреча», «3 дела», «5 записей»."""
    if count == 1:
        return f"{_ONE[noun.gender]} {noun.nominative}"
    return f"{count} {plural(count, noun.counted)}"


def noun_of(event_type: EventType) -> Noun:
    """Существительное для типа записи."""
    return TYPE_NOUNS[event_type]


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _joined(items: Sequence[str]) -> str:
    """«А», «А и Б», «А, Б и В»."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} и {items[-1]}"


# --- Даты и время --------------------------------------------------------------------------

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
WEEKDAY_HORIZON_DAYS = 6
"""До скольких дней вперёд день называется днём недели: «в пятницу, 30 октября»."""
DAYS_PER_WEEK = 7


@dataclass(frozen=True, slots=True)
class _DayWords:
    """Как назвать день: «завтра» / «в пятницу» или «на завтра» / «на пятницу»."""

    named: Mapping[int, str]
    weekdays: tuple[str, ...]
    absolute_prefix: str


_AT_DAY = _DayWords(
    named=MappingProxyType({-1: "вчера", 0: "сегодня", 1: "завтра", 2: "послезавтра"}),
    weekdays=(
        "в понедельник",
        "во вторник",
        "в среду",
        "в четверг",
        "в пятницу",
        "в субботу",
        "в воскресенье",
    ),
    absolute_prefix="",
)
_ONTO_DAY = _DayWords(
    named=MappingProxyType({-1: "на вчера", 0: "на сегодня", 1: "на завтра", 2: "на послезавтра"}),
    weekdays=(
        "на понедельник",
        "на вторник",
        "на среду",
        "на четверг",
        "на пятницу",
        "на субботу",
        "на воскресенье",
    ),
    absolute_prefix="на ",
)


@dataclass(frozen=True, slots=True)
class _DayPhrase:
    text: str
    relative: bool
    """«завтра, 27 октября» — время через запятую; «5 марта 2026» — через пробел."""


def time_text(moment: time) -> str:
    """«15:00», «9:30»."""
    return f"{moment.hour}:{moment.minute:02d}"


def date_text(day: date, today: date) -> str:
    """«27 октября»; с годом, если год другой или день уже прошёл: «5 марта 2026»."""
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    if day.year != today.year or day < today:
        return f"{text} {day.year}"
    return text


def _day_phrase(day: date, today: date, words: _DayWords) -> _DayPhrase:
    offset = (day - today).days
    day_and_month = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    named = words.named.get(offset)
    if named is not None:
        return _DayPhrase(f"{named}, {day_and_month}", relative=True)
    if 0 < offset <= WEEKDAY_HORIZON_DAYS:
        return _DayPhrase(f"{words.weekdays[day.weekday()]}, {day_and_month}", relative=True)
    return _DayPhrase(f"{words.absolute_prefix}{date_text(day, today)}", relative=False)


def _with_time(day: _DayPhrase, time_part: str) -> str:
    separator = ", " if day.relative else " "
    return f"{day.text}{separator}{time_part}"


def when_text(moment: datetime, has_time: bool, today: date) -> str:
    """«завтра, 27 октября, в 15:00», «в пятницу, 30 октября», «5 марта 2026 в 15:45»."""
    day = _day_phrase(moment.date(), today, _AT_DAY)
    return _with_time(day, f"в {time_text(moment.time())}") if has_time else day.text


def onto_text(moment: datetime, has_time: bool, today: date) -> str:
    """Куда перенесли: «на завтра, 27 октября, в 15:00», «на пятницу, 30 октября»."""
    day = _day_phrase(moment.date(), today, _ONTO_DAY)
    return _with_time(day, f"в {time_text(moment.time())}") if has_time else day.text


def schedule_text(card: EventCard, today: date) -> str:
    """Когда запись: «без срока», «завтра, 27 октября, в 15:00», «… с 15:00 до 16:30»."""
    if card.starts_at is None:
        return "без срока"
    if not _has_custom_duration(card):
        return when_text(card.starts_at, card.has_time, today)
    day = _day_phrase(card.starts_at.date(), today, _AT_DAY)
    return _with_time(day, f"с {_time_range(card, ' до ')}")


def _has_custom_duration(card: EventCard) -> bool:
    if card.starts_at is None or card.ends_at is None:
        return False
    return card.ends_at - card.starts_at != DEFAULT_MEETING_DURATION


def _time_range(card: EventCard, separator: str) -> str:
    starts_at = card.starts_at
    ends_at = card.ends_at
    if starts_at is None:
        return ""
    if ends_at is None:
        return time_text(starts_at.time())
    return f"{time_text(starts_at.time())}{separator}{time_text(ends_at.time())}"


def week_text(week_of: date, today: date) -> str:
    """«этой недели», «следующей недели», «недели с 9 ноября»."""
    this_monday = today - timedelta(days=today.weekday())
    if week_of == this_monday:
        return "этой недели"
    if week_of == this_monday + timedelta(days=DAYS_PER_WEEK):
        return "следующей недели"
    return f"недели с {date_text(week_of, today)}"


_SOON_DAYS = MappingProxyType({0: "сегодня", 1: "завтра"})
ONE_DAY = timedelta(days=1)


def _moment_in_period(card: EventCard, period: Period, today: date) -> str:
    """Время записи в сводке за период: за один день — только « в 17:00», иначе и день."""
    if card.starts_at is None:
        return ""
    if period.end - period.start <= ONE_DAY:
        return f" в {time_text(card.starts_at.time())}" if card.has_time else ""
    return f" {_nearest_moment(card, today)}"


def _nearest_moment(card: EventCard, today: date) -> str:
    """Когда ближайшая запись сводки: «сегодня в 16:45», «завтра в 10:00», иначе полностью."""
    starts_at = card.starts_at
    if starts_at is None:
        return ""
    soon = _SOON_DAYS.get((starts_at.date() - today).days)
    if soon is None:
        return when_text(starts_at, card.has_time, today)
    return f"{soon} в {time_text(starts_at.time())}" if card.has_time else soon


# --- Создание и уточнения (Q30) ---------------------------------------------------------------

TITLE_QUESTIONS: Final[Mapping[EventType, str]] = MappingProxyType(
    {
        EventType.TASK: "Как назвать задачу?",
        EventType.REMINDER: "О чём напомнить?",
        EventType.MEETING: "Как назвать встречу?",
    }
)
REMINDER_WHEN_QUESTION = "Когда напомнить?"
REMINDER_TIME_QUESTION = "Во сколько напомнить?"
MEETING_WHEN_QUESTION = "На какой день и время поставить встречу?"
MEETING_TIME_QUESTION = "На какое время поставить встречу?"
MEETING_DAY_QUESTION = "На какой день поставить встречу?"


def reminder_week_day_question(week: str) -> str:
    """«В какой день следующей недели напомнить?»."""
    return f"В какой день {week} напомнить?"


def meeting_week_day_question(week: str) -> str:
    """«На какой день следующей недели?»."""
    return f"На какой день {week}?"


def created(card: EventCard, today: date) -> str:
    """«Встреча «Встреча с командой» — завтра, 27 октября, в 15:00.»."""
    noun = noun_of(card.type)
    return f"{_capitalized(noun.nominative)} «{card.title}» — {schedule_text(card, today)}."


# --- Конфликты встреч --------------------------------------------------------------------------

ADD_ANYWAY = "Всё равно добавить?"
MOVE_ANYWAY = "Всё равно перенести?"


def duplicate_question(existing: EventCard, today: date) -> str:
    """«Такое напоминание уже есть: «Позвонить Ивану» — завтра в 10:00. Добавить ещё одно?»."""
    noun = noun_of(existing.type)
    moment = _nearest_moment(existing, today) or "без срока"
    return (
        f"{_capitalized(_SUCH[noun.gender])} {noun.nominative} уже есть: «{existing.title}» — "
        f"{moment}. Добавить {_ONE_MORE[noun.gender]}?"
    )


def conflict_question(conflicts: Sequence[EventCard], question: str) -> str:
    """«В это время уже стоит «Планёрка» (15:00-16:00). Всё равно добавить?», тире — `EN_DASH`."""
    meetings = [f"«{card.title}» ({_time_range(card, EN_DASH)})" for card in conflicts]
    verb = "стоит" if len(meetings) == 1 else "стоят"
    return f"В это время уже {verb} {_joined(meetings)}. {question}"


# --- Список за период ------------------------------------------------------------------------

_PREPOSITIONS = frozenset({"на", "в", "во", "за", "с", "со", "до", "к", "ко", "по"})


def list_summary(
    events: Sequence[EventCard], period: Period, now: datetime, asked_type: EventType | None
) -> str:
    """Сводка за период: «Сегодня у вас 3 дела: 2 встречи и задача. Ближайшее — «…» в 17:00.»."""
    if not events:
        missing = noun_of(asked_type).genitive_plural if asked_type else "ничего"
        return f"{_closed(_empty_period(period.label))} {missing} нет."
    today = now.date()
    types = {card.type for card in events}
    noun = noun_of(next(iter(types))) if len(types) == 1 else THING
    heading = f"{_closed(_capitalized(period.label))} у вас {count_phrase(len(events), noun)}"
    if len(events) == 1:
        return f"{heading}: «{events[0].title}»{_moment_in_period(events[0], period, today)}."
    sentences = [f"{heading}{_breakdown(events) if noun is THING else ''}."]
    nearest = _nearest_upcoming(events, now)
    if nearest is not None:
        lead = _capitalized(_NEAREST[noun.gender])
        sentences.append(f"{lead} — «{nearest.title}» {_nearest_moment(nearest, today)}.")
    sentences.extend(_done_note(events))
    return " ".join(sentences)


def _closed(lead: str) -> str:
    """Период с уточнением через запятую закрывается запятой: «На пятницу, 30 октября, у вас…»."""
    return f"{lead}," if "," in lead else lead


_DAY_PARTS = frozenset({"утром", "днём", "днем", "вечером", "ночью"})
"""Подпись с частью суток уже обстоятельство времени: «Завтра вечером ничего нет», без «На»."""


def _empty_period(label: str) -> str:
    words = label.lower().replace(",", " ").split()
    if (words and words[0] in _PREPOSITIONS) or (words and words[-1] in _DAY_PARTS):
        return _capitalized(label)
    return f"На {label}"


def _breakdown(events: Sequence[EventCard]) -> str:
    """«: 2 встречи и задача»."""
    parts = []
    for event_type in TYPE_ORDER:
        count = sum(1 for card in events if card.type is event_type)
        if count == 1:
            parts.append(noun_of(event_type).nominative)
        elif count > 1:
            parts.append(f"{count} {plural(count, noun_of(event_type).counted)}")
    return f": {_joined(parts)}"


def _nearest_upcoming(events: Sequence[EventCard], now: datetime) -> EventCard | None:
    """Первая невыполненная запись со временем, которая ещё не началась."""
    upcoming = [
        (card.starts_at, card)
        for card in events
        if card.status is EventStatus.OPEN
        and card.has_time
        and card.starts_at is not None
        and card.starts_at >= now
    ]
    return min(upcoming, key=itemgetter(0))[1] if upcoming else None


def _done_note(events: Sequence[EventCard]) -> list[str]:
    done = sum(1 for card in events if card.status is EventStatus.DONE)
    if done == 0:
        return []
    if done == len(events):
        return ["Всё уже сделано."]
    return [f"Сделано {done} из {len(events)}."]


# --- Поиск -------------------------------------------------------------------------------------

SEARCH_NOTHING = "Не нашёл похожих записей. Попробуйте сказать иначе."


def search_latest_past(card: EventCard, today: date) -> str:
    """«Последняя встреча «…» была 5 марта 2026 в 15:45.»."""
    noun = noun_of(card.type)
    moment = schedule_text(card, today)
    return (
        f"{_capitalized(_LATEST[noun.gender])} {noun.nominative} «{card.title}» "
        f"{_WAS[noun.gender]} {moment}."
    )


def search_nearest_future(card: EventCard, today: date) -> str:
    """«Ближайшая встреча «…» будет завтра, 27 октября, в 15:00.»."""
    noun = noun_of(card.type)
    moment = schedule_text(card, today)
    return f"{_capitalized(_NEAREST[noun.gender])} {noun.nominative} «{card.title}» будет {moment}."


def search_no_past(card: EventCard, today: date) -> str:
    """Спросили «когда была», а есть только будущая."""
    return f"Раньше такого не было. {search_nearest_future(card, today)}"


def search_no_future(card: EventCard, today: date) -> str:
    """Спросили «когда будет», а есть только прошедшая."""
    return f"Впереди такого нет. {search_latest_past(card, today)}"


def search_undated(card: EventCard) -> str:
    """Нашлась только запись без даты."""
    return f"Нашёл {noun_of(card.type).accusative} «{card.title}» — без срока."


def search_found(total: int, best: EventCard, today: date, *, capped: bool = False) -> str:
    """«Нашёл 4 записи. Больше всего подходит — задача «…», 14 апреля 2024.».

    Не «ближе всего»: рядом с датой это читалось бы как «ближайшая по времени».

    `capped` — поиск упёрся в предел выдачи: точное число («Нашёл 50 записей») звучало бы
    как отчёт базы данных, поэтому говорим «много похожих».
    """
    best_text = f"{noun_of(best.type).nominative} «{best.title}», {schedule_text(best, today)}"
    if total == 1:
        return f"Нашёл одну запись: {best_text}."
    if capped:
        return f"Нашёл много похожих записей. Больше всего подходит — {best_text}."
    return f"Нашёл {count_phrase(total, ENTRY)}. Больше всего подходит — {best_text}."


# --- Изменение записей -------------------------------------------------------------------------

TARGET_UNCLEAR = (
    "Не понял, о какой записи речь. Назовите её — например: «Перенеси встречу с Иваном на завтра»."
)
EVENT_GONE = "Этой записи уже нет."
_CHOICE_VERBS: Final[Mapping[Action, str]] = MappingProxyType(
    {
        Action.RESCHEDULE: "перенести",
        Action.RENAME: "переименовать",
        Action.DELETE: "удалить",
    }
)


NOTHING_AT_MOMENT = (
    "Не нашёл записи в названное время. Назовите её — например: «Перенеси встречу с Иваном"
    " на завтра»."
)


def target_not_found(query: str) -> str:
    """Поиск цели команды ничего не дал."""
    return f"Не нашёл ничего похожего на «{query}». Попробуйте сказать иначе."


def unhandled_commands(rest: str) -> str:
    """Остальные команды реплики: выполняется только первая, их нужно повторить отдельно."""
    return f"А «{rest}» пока не сделал: выполняю по одной команде — скажите это отдельно."


def _choice_verb(action: Action, noun: Noun) -> str:
    if action is Action.COMPLETE:
        return f"отметить {_DONE[noun.gender]}"
    return _CHOICE_VERBS.get(action, "выбрать")


def choice_question(action: Action, noun: Noun) -> str:
    """«Какую встречу перенести?»."""
    return f"{_capitalized(_WHICH[noun.gender])} {noun.accusative} {_choice_verb(action, noun)}?"


def choice_text(action: Action, noun: Noun, shown: int, total: int) -> str:
    """«Нашёл 3 встречи. Какую перенести?»; если показаны не все — «вот самые похожие»."""
    question = f"{_capitalized(_WHICH[noun.gender])} {_choice_verb(action, noun)}?"
    if total > shown:
        return f"Подходит несколько записей, вот самые похожие. {question}"
    return f"Нашёл {count_phrase(shown, noun)}. {question}"


def choice_out_of_range(count: int) -> str:
    """Выбрали номер, которого нет в списке."""
    return f"Такого варианта нет — назовите номер от 1 до {count}."


def reschedule_when_question(card: EventCard) -> str:
    """«На когда перенести встречу «Планёрка»?»."""
    return f"На когда перенести {noun_of(card.type).accusative} «{card.title}»?"


def reschedule_week_day_question(week: str) -> str:
    """«На какой день следующей недели перенести?»."""
    return f"На какой день {week} перенести?"


def rename_question(card: EventCard) -> str:
    """«Как теперь назвать задачу «Отчёт»?»."""
    return f"Как теперь назвать {noun_of(card.type).accusative} «{card.title}»?"


def rescheduled(card: EventCard, today: date) -> str:
    """«Перенёс встречу «…» на четверг, 29 октября, в 16:00.»."""
    if card.starts_at is None:
        return f"Убрал срок у задачи «{card.title}»."
    moment = onto_text(card.starts_at, card.has_time, today)
    return f"Перенёс {noun_of(card.type).accusative} «{card.title}» {moment}."


def renamed(old_title: str, card: EventCard) -> str:
    """«Переименовал: «Отчёт» теперь называется «Отчёт Ольге».»."""
    return f"Переименовал: «{old_title}» теперь называется «{card.title}»."


def completed(card: EventCard) -> str:
    """Отметка о выполнении."""
    return f"Отметил как сделанное: «{card.title}»."


def already_completed(card: EventCard) -> str:
    """Запись уже выполнена — менять нечего."""
    return f"«{card.title}» уже отмечено как сделанное."


def delete_question(card: EventCard, today: date) -> str:
    """«Удалить встречу «…» — сегодня, 26 октября, в 17:00?» (Q33: удаление переспрашиваем)."""
    subject = f"{noun_of(card.type).accusative} «{card.title}»"
    if card.starts_at is None:
        return f"Удалить {subject}?"
    return f"Удалить {subject} — {schedule_text(card, today)}?"


def deleted(card: EventCard) -> str:
    """Запись удалена."""
    return f"Удалил {noun_of(card.type).accusative} «{card.title}»."


# --- Отказ и повтор вопроса ---------------------------------------------------------------------

DECLINED_CREATE = "Хорошо, не добавляю."
DECLINED_MOVE = "Хорошо, оставляю как было."
DECLINED_DELETE = "Хорошо, не удаляю."
DECLINED_CHANGE = "Хорошо, ничего не меняю."
_DECLINED_CONFIRMATIONS: Final[Mapping[Action, str]] = MappingProxyType(
    {
        Action.CREATE: DECLINED_CREATE,
        Action.RESCHEDULE: DECLINED_MOVE,
        Action.DELETE: DECLINED_DELETE,
    }
)


def declined(expects: PendingExpectation, action: Action) -> str:
    """Ответ на «нет» / «не надо», когда ассистент чего-то ждал."""
    if expects is PendingExpectation.CONFIRM:
        return _DECLINED_CONFIRMATIONS.get(action, DECLINED_CHANGE)
    return DECLINED_CREATE if action is Action.CREATE else DECLINED_CHANGE


# --- Отмена действия ---------------------------------------------------------------------------

NOTHING_TO_UNDO = "Отменять нечего."
UNDO_EXPIRED = "Отменить уже нельзя."


def undo_removed(title: str) -> str:
    """Отменено создание записи."""
    return f"Отменил: «{title}» больше нет в плане."


def undo_reverted(card: EventCard, today: date) -> str:
    """Отменено изменение: запись снова такая, как была."""
    noun = noun_of(card.type)
    return f"Вернул как было: {noun.nominative} «{card.title}» — {schedule_text(card, today)}."


def undo_restored(card: EventCard) -> str:
    """Отменено удаление."""
    return f"Вернул {noun_of(card.type).accusative} «{card.title}»."


# --- Подсказки ---------------------------------------------------------------------------------

EXAMPLE_PHRASES = (
    "«Напомни завтра в 10 позвонить Ивану»",
    "«Что у меня сегодня?»",
    "«Найди задачу про презентацию»",
)
_EXAMPLES = f"{EXAMPLE_PHRASES[0]}, {EXAMPLE_PHRASES[1]} или {EXAMPLE_PHRASES[2]}"
SMALLTALK = f"Я Горький — веду ваши задачи, напоминания и встречи. Скажите, например: {_EXAMPLES}."
NOT_UNDERSTOOD = f"Не понял, что сделать. Скажите, например: {_EXAMPLES}."
OFF_TOPIC = (
    "Это не по моей части: я веду задачи, напоминания и встречи. "
    f"Скажите, например: {EXAMPLE_PHRASES[1]} или {EXAMPLE_PHRASES[0]}."
)
"""Реплика не про задачи и встречи («какая завтра погода?»), и ассистент ни о чём не спрашивал."""
NOTHING_TO_DECLINE = "Хорошо, ничего не делаю."
"""«Нет, не надо», когда ассистент ни о чём не спрашивал."""
REPLY_NOT_UNDERSTOOD = "Не понял ответ."
"""Начало повторного вопроса, если ответ на него не разобран."""
