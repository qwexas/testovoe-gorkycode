"""Контракт понимания реплик между ИИ-частью и бизнес-логикой диалога.

Разделение ответственности:
- `IntentParser` (ИИ-часть, `app/nlu`) — LLM извлекает смысл реплики, а код парсера
  переводит «завтра», «в пятницу», «утром», «через два часа» в конкретные даты и время
  по правилам Q31. Парсер НЕ решает, чего не хватает, и НЕ задаёт вопросов.
- Бизнес-логика диалога (`app/core/dialog`) по `Intent` решает, что делать: создать,
  уточнить (правила Q30), переспросить при удалении (Q33), показать выбор и т. д.

Все даты и время — по Москве (`Europe/Moscow`), наивные `date`/`time` трактуются так же.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.core.enums import EventStatus, EventType, PendingExpectation


class Action(StrEnum):
    """Что пользователь хочет сделать."""

    CREATE = "create"
    """Создать задачу, напоминание или встречу."""
    LIST = "list"
    """Показать записи за период: «Что у меня сегодня?», «Какие задачи на завтра?»."""
    SEARCH = "search"
    """Найти записи по смыслу: «Найди задачу про презентацию», «Когда была встреча с Иваном?»."""
    RESCHEDULE = "reschedule"
    """Перенести на другое время: «Перенеси её на завтра», «Сдвинь созвон на 16:00»."""
    RENAME = "rename"
    """Изменить название: «Переименуй задачу в „Отправить отчёт Ольге“»."""
    COMPLETE = "complete"
    """Отметить выполненной: «Отметь звонок Ивану как сделанный»."""
    DELETE = "delete"
    """Удалить запись (бизнес-логика всегда переспрашивает)."""
    ANSWER = "answer"
    """Ответ на уточняющий вопрос: «в 15:00», «на пятницу», «Созвон с отделом продаж»."""
    CHOOSE = "choose"
    """Выбор из предложенных вариантов: «вторую», «ту, что с Ольгой»."""
    CONFIRM = "confirm"
    """Согласие: «да», «удаляй», «всё равно добавь»."""
    DENY = "deny"
    """Отказ: «нет», «не надо», «отмена»."""
    UNDO = "undo"
    """Отменить последнее действие: «отмени», «верни как было»."""
    SMALLTALK = "smalltalk"
    """Приветствие, благодарность, «что ты умеешь?»."""
    UNKNOWN = "unknown"
    """Не про задачи и встречи или не удалось понять."""


class TimeScope(StrEnum):
    """Про какое время спрашивают при поиске."""

    PAST = "past"
    """«Когда у меня БЫЛА встреча с Иваном?»"""
    FUTURE = "future"
    """«Когда у меня БУДЕТ созвон с партнёром?»"""
    ANY = "any"


@dataclass(frozen=True, slots=True)
class When:
    """Момент, названный пользователем, уже переведённый в конкретные значения.

    Пустые поля значат «не названо» — по ним бизнес-логика решает, нужно ли уточнение.
    """

    date: dt.date | None = None
    """День. Для «до конца недели» — воскресенье этой недели (время 23:59 — в `time`)."""
    time: dt.time | None = None
    """Время. `None` — время не названо («завтра», «в пятницу»)."""
    week_of: dt.date | None = None
    """Понедельник недели, если известна только неделя («на следующей неделе»), а день — нет."""

    @property
    def is_empty(self) -> bool:
        """Ничего не названо."""
        return self.date is None and self.time is None and self.week_of is None


@dataclass(frozen=True, slots=True)
class Period:
    """Полуинтервал времени `[start, end)` для списков и фильтра поиска."""

    start: dt.datetime
    end: dt.datetime
    label: str
    """Как назвать период пользователю: «сегодня», «на завтра», «на этой неделе»."""


@dataclass(frozen=True, slots=True)
class TargetRef:
    """На какую запись ссылается команда изменения (перенос, удаление, отметка...)."""

    last: bool = False
    """Местоимение: «её», «эту встречу», «последнюю» — запись из контекста диалога."""
    query: str | None = None
    """Описание записи: «встречу с Иваном», «задачу про отчёт»."""
    event_type: EventType | None = None
    when: When | None = None
    """Когда стоит запись сейчас: «завтрашний созвон», «встречу в четверг», «созвон в 15».

    У переноса это прежние день и время записи, а новые — в `Intent.when`. Ссылка без
    описания и без местоимения, но с `when` («перенеси завтрашнюю встречу в 10…») —
    запись ищется по дню и времени."""


@dataclass(frozen=True, slots=True)
class Intent:
    """Смысл одной реплики пользователя."""

    action: Action
    text: str
    """Исходная реплика (после распознавания речи)."""
    event_type: EventType | None = None
    """Тип создаваемой записи или тип, о котором спрашивают/который ищут."""
    title: str | None = None
    """Название создаваемой записи, новое название при RENAME, название в ответе на уточнение."""
    when: When | None = None
    """CREATE: когда; RESCHEDULE: новое время; ANSWER: названные дата/время."""
    duration_minutes: int | None = None
    """Длительность встречи, если названа: «на полчаса», «с 15 до 17».

    RESCHEDULE: новая длительность («перенеси на 17:00 на полчаса»); `None` — прежняя."""
    period: Period | None = None
    """LIST: за какой период; SEARCH: необязательный фильтр («в прошлом месяце»)."""
    status: EventStatus | None = None
    """Фильтр статуса: «невыполненные задачи», «что я уже сделал»."""
    query: str | None = None
    """SEARCH: что искать, без служебных слов («встреча с Иваном», «договор»)."""
    time_scope: TimeScope = TimeScope.ANY
    target: TargetRef | None = None
    """RESCHEDULE / RENAME / COMPLETE / DELETE: какую запись менять."""
    choice_index: int | None = None
    """CHOOSE: номер варианта с 1 («вторую» → 2)."""
    unhandled: str | None = None
    """Остальные команды реплики: «перенеси X на 17 и удали Y» → «удали Y».

    `Intent` описывает только первую команду; остальные бизнес-логика не выполняет,
    а честно называет пользователю, чтобы он повторил их отдельно."""


@dataclass(frozen=True, slots=True)
class ContextEvent:
    """Запись, упомянутая в диалоге недавно (для «её», «эту», «вторую»)."""

    id: int
    type: EventType
    title: str
    starts_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class DialogTurn:
    """Реплика из недавней истории диалога."""

    role: str
    """`user` или `assistant`."""
    text: str


@dataclass(frozen=True, slots=True)
class DialogContext:
    """Всё, что парсеру нужно знать о диалоге, кроме самой реплики."""

    now: dt.datetime
    """Текущий момент (Москва). Тесты и eval подставляют фиксированное значение."""
    pending: PendingExpectation | None = None
    """Ассистент задал вопрос и ждёт: времени, даты, выбора, подтверждения..."""
    pending_question: str | None = None
    """Текст заданного вопроса — помогает понять короткий ответ («в три»)."""
    recent: Sequence[DialogTurn] = field(default_factory=tuple)
    """Последние реплики (до 6), старые первыми."""
    focus: Sequence[ContextEvent] = field(default_factory=tuple)
    """Записи в фокусе.

    Последняя созданная, изменённая или найденная запись — первой; варианты выбора — по порядку.
    """


class IntentParser(Protocol):
    """Превращает реплику пользователя в `Intent`."""

    async def parse(self, text: str, context: DialogContext) -> Intent:
        """Разбирает реплику. Если LLM недоступна — `DomainError` с кодом `llm_unavailable`."""
        ...
