"""Правила диалога о времени: чего не хватает (Q30) и что подставить по умолчанию (Q31).

Парсер уже перевёл «завтра», «в пятницу», «через два часа» в даты и время (`When`);
здесь решается, хватает ли этого, и считается итоговое время записи.

- Задача: дата необязательна («без срока»); «на следующей неделе» — срок вс 23:59 той недели.
- Напоминание: нужны дата и время. Ничего — «Когда напомнить?», только дата — «Во сколько?».
- Встреча: нужны дата и время; «на следующей неделе» — уточнить день; длится 60 мин.
- Названо только время («в 18») — ближайшее такое время: сегодня, а если прошло — завтра.
  У встречи без даты спрашиваем день.
"""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Final

from app.core.dialog import phrases
from app.core.dialog.models import PendingQuestion
from app.core.enums import EventType, PendingExpectation
from app.core.events import EventCard, EventDraft
from app.core.schedule import DEFAULT_MEETING_DURATION, MOSCOW, Schedule
from app.nlu.interfaces import Intent, When

DEFAULT_CREATED_TYPE = EventType.TASK
"""Тип записи, если разбор его не назвал: «Поставь на завтра купить молоко» — задача."""
DEADLINE_TIME = time(23, 59)
"""Срок задачи «до конца недели» / «на следующей неделе» — воскресенье, 23:59 (Q31)."""
SUNDAY_OFFSET = timedelta(days=6)
ONE_DAY = timedelta(days=1)
TITLE_TRAILING = " .!?,;:«»\"'"

QuestionRule = Callable[[When, date], PendingQuestion | None]


def created_type(intent: Intent) -> EventType:
    """Тип создаваемой записи."""
    return intent.event_type or DEFAULT_CREATED_TYPE


def tidy_title(title: str | None) -> str | None:
    """Название без лишних пробелов, кавычек и точки в конце, с заглавной буквы."""
    if title is None:
        return None
    cleaned = " ".join(title.split()).strip(TITLE_TRAILING)
    return cleaned[:1].upper() + cleaned[1:] if cleaned else None


def creation_question(intent: Intent, today: date) -> PendingQuestion | None:
    """Чего не хватает для создания записи (Q30); `None` — данных достаточно."""
    event_type = created_type(intent)
    if not intent.title:
        return PendingQuestion(PendingExpectation.TITLE, phrases.TITLE_QUESTIONS[event_type])
    return _QUESTION_RULES[event_type](intent.when or When(), today)


def _task_question(when: When, today: date) -> PendingQuestion | None:
    return None


def _reminder_question(when: When, today: date) -> PendingQuestion | None:
    if when.date is None and when.time is None:
        if when.week_of is not None:
            week = phrases.week_text(when.week_of, today)
            return _ask(PendingExpectation.DATE, phrases.reminder_week_day_question(week))
        return _ask(PendingExpectation.DATETIME, phrases.REMINDER_WHEN_QUESTION)
    if when.time is None:
        return _ask(PendingExpectation.TIME, phrases.REMINDER_TIME_QUESTION)
    return None


def _meeting_question(when: When, today: date) -> PendingQuestion | None:
    if when.date is None and when.week_of is not None:
        week = phrases.week_text(when.week_of, today)
        return _ask(PendingExpectation.DATE, phrases.meeting_week_day_question(week))
    if when.date is None and when.time is None:
        return _ask(PendingExpectation.DATETIME, phrases.MEETING_WHEN_QUESTION)
    if when.date is None:
        return _ask(PendingExpectation.DATE, phrases.MEETING_DAY_QUESTION)
    if when.time is None:
        return _ask(PendingExpectation.TIME, phrases.MEETING_TIME_QUESTION)
    return None


_QUESTION_RULES: Final[Mapping[EventType, QuestionRule]] = MappingProxyType(
    {
        EventType.TASK: _task_question,
        EventType.REMINDER: _reminder_question,
        EventType.MEETING: _meeting_question,
    }
)


def _ask(expects: PendingExpectation, question: str) -> PendingQuestion:
    return PendingQuestion(expects, question)


def creation_draft(intent: Intent, now: datetime) -> EventDraft:
    """Запись по полному разбору (после `creation_question`, вернувшего `None`)."""
    event_type = created_type(intent)
    title = tidy_title(intent.title) or ""
    when = intent.when or When()
    if when.is_empty:
        return EventDraft(type=event_type, title=title, starts_at=None, has_time=False)
    schedule = _moment(when, None, now)
    ends_at = None
    if event_type is EventType.MEETING and schedule.starts_at is not None:
        ends_at = schedule.starts_at + _meeting_duration(intent)
    return EventDraft(
        type=event_type,
        title=title,
        starts_at=schedule.starts_at,
        has_time=schedule.has_time,
        ends_at=ends_at,
    )


def _meeting_duration(intent: Intent) -> timedelta:
    if intent.duration_minutes:
        return timedelta(minutes=intent.duration_minutes)
    return DEFAULT_MEETING_DURATION


def reschedule_question(card: EventCard, when: When | None, today: date) -> PendingQuestion | None:
    """Чего не хватает для переноса записи; `None` — новое время понятно."""
    if when is None or when.is_empty:
        return _ask(PendingExpectation.DATETIME, phrases.reschedule_when_question(card))
    needs_day = card.type is not EventType.TASK
    if when.date is None and when.week_of is not None and needs_day:
        week = phrases.week_text(when.week_of, today)
        return _ask(PendingExpectation.DATE, phrases.reschedule_week_day_question(week))
    return None


def rescheduled_schedule(card: EventCard, when: When, now: datetime) -> Schedule:
    """Новое время записи: названное время — на прежний день, названный день — в прежнее время."""
    return _moment(when, card, now)


def _moment(when: When, current: EventCard | None, now: datetime) -> Schedule:
    """Начало записи по названному дню и времени; недостающее берётся из `current`."""
    clock_time: time | None
    if when.date is None and when.week_of is not None:
        day, clock_time = when.week_of + SUNDAY_OFFSET, when.time or DEADLINE_TIME
    else:
        clock_time = when.time or _current_time(current)
        day = when.date or _current_day(current) or _nearest_day(clock_time, now)
    starts_at = datetime.combine(day, clock_time or time.min, tzinfo=MOSCOW)
    return Schedule(starts_at=starts_at, has_time=clock_time is not None)


def _current_time(current: EventCard | None) -> time | None:
    if current is None or current.starts_at is None or not current.has_time:
        return None
    return current.starts_at.time()


def _current_day(current: EventCard | None) -> date | None:
    if current is None or current.starts_at is None:
        return None
    return current.starts_at.date()


def _nearest_day(clock_time: time | None, now: datetime) -> date:
    """День ближайшего наступления времени: сегодня, а если оно прошло — завтра."""
    today = now.date()
    if clock_time is None or clock_time > now.time():
        return today
    return today + ONE_DAY


def merge_when(base: When | None, answer: When | None) -> When:
    """Дополняет названное раньше тем, что пользователь назвал в ответе."""
    if base is None:
        return answer or When()
    if answer is None:
        return base
    day = answer.date or base.date
    return When(
        date=day,
        time=answer.time or base.time,
        week_of=None if day else (answer.week_of or base.week_of),
    )


def merge_answer(pending: Intent, answer: Intent, expects: PendingExpectation) -> Intent:
    """Отложенное действие, дополненное ответом на уточняющий вопрос.

    На вопрос о названии ответом считается вся реплика, если разбор не выделил название.
    """
    title = pending.title
    if expects is PendingExpectation.TITLE:
        title = tidy_title(answer.title or answer.text)
    elif not title:
        title = answer.title
    return replace(
        pending,
        title=title,
        when=merge_when(pending.when, answer.when),
        duration_minutes=answer.duration_minutes or pending.duration_minutes,
    )


def resolved_when(schedule: Schedule) -> When:
    """`When` с полностью названными днём и временем — для отложенного подтверждения."""
    if schedule.starts_at is None:
        return When()
    moment = schedule.starts_at.astimezone(MOSCOW)
    return When(date=moment.date(), time=moment.time() if schedule.has_time else None)
