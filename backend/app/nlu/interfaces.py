"""контракт понимания реплик между ИИ-частью и бизнес-логикой диалога.

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
    """создать задачу, напоминание или встречу."""
    LIST = "list"
    """показать записи за период: «Что у меня сегодня?», «Какие задачи на завтра?»."""
    SEARCH = "search"
    """найти записи по смыслу: «Найди задачу про презентацию», «Когда была встреча с Иваном?»."""
    RESCHEDULE = "reschedule"
    """перенести на другое время: «Перенеси её на завтра», «Сдвинь созвон на 16:00»."""
    RENAME = "rename"
    """изменить название: «Переименуй задачу в „Отправить отчёт Ольге“»."""
    COMPLETE = "complete"
    """отметить выполненной: «Отметь звонок Ивану как сделанный»."""
    DELETE = "delete"
    """удалить запись (бизнес-логика всегда переспрашивает)."""
    ANSWER = "answer"
    """ответ на уточняющий вопрос: «в 15:00», «на пятницу», «Созвон с отделом продаж»."""
    CHOOSE = "choose"
    """выбор из предложенных вариантов: «вторую», «ту, что с Ольгой»."""
    CONFIRM = "confirm"
    """согласие: «да», «удаляй», «всё равно добавь»."""
    DENY = "deny"
    """отказ: «нет», «не надо», «отмена»."""
    UNDO = "undo"
    """отменить последнее действие: «отмени», «верни как было»."""
    SMALLTALK = "smalltalk"
    """приветствие, благодарность, «что ты умеешь?»."""
    UNKNOWN = "unknown"
    """не про задачи и встречи или не удалось понять."""


class TimeScope(StrEnum):
    """Про какое время спрашивают при поиске."""

    PAST = "past"
    """«Когда у меня БЫЛА встреча с Иваном?»"""
    FUTURE = "future"
    """«Когда у меня БУДЕТ созвон с партнёром?»"""
    ANY = "any"


@dataclass(frozen=True, slots=True)
class When:
    """момент, названный пользователем, уже переведённый в конкретные значения.

    Пустые поля значат «не названо» — по ним бизнес-логика решает, нужно ли уточнение.
    """

    date: dt.date | None = None
    """день. Для «до конца недели» — воскресенье этой недели (время 23:59 — в `time`)."""
    time: dt.time | None = None
    """время. `None` — время не названо («завтра», «в пятницу»)."""
    week_of: dt.date | None = None
    """понедельник недели, если известна только неделя («на следующей неделе»), а день — нет."""

    @property
    def is_empty(self) -> bool:
        """ничего не названо."""
        return self.date is None and self.time is None and self.week_of is None


@dataclass(frozen=True, slots=True)
class Period:
    """полуинтервал времени `[start, end)` для списков и фильтра поиска."""

    start: dt.datetime
    end: dt.datetime
    label: str
    """как назвать период пользователю: «сегодня», «на завтра», «на этой неделе»."""


@dataclass(frozen=True, slots=True)
class TargetRef:
    """на какую запись ссылается команда изменения (перенос, удаление, отметка...)."""

    last: bool = False
    """местоимение: «её», «эту встречу», «последнюю» — запись из контекста диалога."""
    query: str | None = None
    """описание записи: «встречу с Иваном», «задачу про отчёт»."""
    event_type: EventType | None = None
    when: When | None = None
    """когда стоит запись сейчас: «завтрашний созвон», «встречу в четверг», «созвон в 15».

    У переноса это прежние день и время записи, а новые — в `Intent.when`. Ссылка без
    описания и без местоимения, но с `when` («перенеси завтрашнюю встречу в 10…») —
    запись ищется по дню и времени."""


@dataclass(frozen=True, slots=True)
class Intent:
    """смысл одной реплики пользователя."""

    action: Action
    text: str
    """исходная реплика (после распознавания речи)."""
    event_type: EventType | None = None
    """тип создаваемой записи или тип, о котором спрашивают/который ищут."""
    title: str | None = None
    """название создаваемой записи, новое название при RENAME, название в ответе на уточнение."""
    when: When | None = None
    """CREATE: когда; RESCHEDULE: новое время; ANSWER: названные дата/время."""
    duration_minutes: int | None = None
    """длительность встречи, если названа: «на полчаса», «с 15 до 17».

    RESCHEDULE: новая длительность («перенеси на 17:00 на полчаса»); `None` — прежняя."""
    period: Period | None = None
    """LIST: за какой период; SEARCH: необязательный фильтр («в прошлом месяце»)."""
    status: EventStatus | None = None
    """фильтр статуса: «невыполненные задачи», «что я уже сделал»."""
    query: str | None = None
    """SEARCH: что искать, без служебных слов («встреча с Иваном», «договор»)."""
    time_scope: TimeScope = TimeScope.ANY
    target: TargetRef | None = None
    """RESCHEDULE / RENAME / COMPLETE / DELETE: какую запись менять."""
    choice_index: int | None = None
    """CHOOSE: номер варианта с 1 («вторую» → 2)."""
    unhandled: str | None = None
    """остальные команды реплики: «перенеси X на 17 и удали Y» → «удали Y».

    `Intent` описывает только первую команду; остальные бизнес-логика не выполняет,
    а честно называет пользователю, чтобы он повторил их отдельно."""


@dataclass(frozen=True, slots=True)
class ContextEvent:
    """запись, упомянутая в диалоге недавно (для «её», «эту», «вторую»)."""

    id: int
    type: EventType
    title: str
    starts_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class DialogTurn:
    """реплика из недавней истории диалога."""

    role: str
    """`user` или `assistant`."""
    text: str


@dataclass(frozen=True, slots=True)
class DialogContext:
    """всё, что парсеру нужно знать о диалоге, кроме самой реплики."""

    now: dt.datetime
    """текущий момент (Москва). Тесты и eval подставляют фиксированное значение."""
    pending: PendingExpectation | None = None
    """ассистент задал вопрос и ждёт: времени, даты, выбора, подтверждения..."""
    pending_question: str | None = None
    """текст заданного вопроса — помогает понять короткий ответ («в три»)."""
    recent: Sequence[DialogTurn] = field(default_factory=tuple)
    """последние реплики (до 6), старые первыми."""
    focus: Sequence[ContextEvent] = field(default_factory=tuple)
    """записи в фокусе.

    Последняя созданная, изменённая или найденная запись — первой; варианты выбора — по порядку.
    """


class IntentParser(Protocol):
    """превращает реплику пользователя в `Intent`."""

    async def parse(self, text: str, context: DialogContext) -> Intent:
        """разбирает реплику. Если LLM недоступна — `DomainError` с кодом `llm_unavailable`."""
        ...
