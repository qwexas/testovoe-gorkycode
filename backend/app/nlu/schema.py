"""плоская схема ответа LLM. Даты и время вычисляются в `time_resolution`.

Обязателен только `action`: остальные поля модель может пропустить.
Непонятное значение поля считается отсутствующим, чтобы не отклонять весь ответ.
"""

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, field_validator
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

from app.nlu.expressions import DateExpression, DateKind, DayPart, TimeExpression
from app.nlu.interfaces import Action, TimeScope

logger = logging.getLogger(__name__)


class EventTypeName(StrEnum):
    """Тип записи в ответе модели; `none` — тип не назван («что у меня сегодня»)."""

    NONE = "none"
    TASK = "task"
    REMINDER = "reminder"
    MEETING = "meeting"


class StatusName(StrEnum):
    """Фильтр статуса в ответе модели."""

    NONE = "none"
    OPEN = "open"
    DONE = "done"


DAY_PART_WORDS: dict[str, DayPart] = {
    **{part.value: part for part in DayPart if part is not DayPart.NONE},
    "утро": DayPart.MORNING,
    "утром": DayPart.MORNING,
    "день": DayPart.DAY,
    "днём": DayPart.DAY,
    "днем": DayPart.DAY,
    "обед": DayPart.DAY,
    "вечер": DayPart.EVENING,
    "вечером": DayPart.EVENING,
    "ночь": DayPart.NIGHT,
    "ночью": DayPart.NIGHT,
}
"""Часть суток словом — английское значение `DayPart` или русское «утром», «вечером»."""


class Extraction(BaseModel):
    """Ответ модели по `EXTRACTION_SCHEMA`."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    action: Action = Action.UNKNOWN
    event_type: EventTypeName = EventTypeName.NONE
    query: str = ""
    about_last: bool = False
    target_date: DateKind = DateKind.NONE
    target_time: str = ""
    title: str = ""
    new_title: str = ""
    date: DateKind = DateKind.NONE
    date_value: str = ""
    time: str = ""
    day_part: DayPart = DayPart.NONE
    in_minutes: int = 0
    duration_minutes: int = 0
    time_scope: TimeScope = TimeScope.ANY
    status: StatusName = StatusName.NONE
    choice: int = 0
    rest: str = ""

    @field_validator("*", mode="wrap")
    @classmethod
    def _unreadable_means_not_named(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        try:
            return handler(value)
        except ValidationError:
            field_name = info.field_name or ""
            logger.warning("Поле %s в ответе модели не по схеме: считаем не названным", field_name)
            return cls.model_fields[field_name].default

    @property
    def date_expression(self) -> DateExpression:
        """Названный день — новый для создания и переноса, день записи для остальных."""
        return DateExpression(kind=self.date, value=self.date_value)

    @property
    def target_date_expression(self) -> DateExpression:
        """День, на котором переносимая запись стоит сейчас."""
        return DateExpression(kind=self.target_date)

    @property
    def target_time_expression(self) -> TimeExpression:
        """Время, в которое переносимая запись стоит сейчас.

        Часть суток к нему не относится: `day_part` описывает новое время, поэтому модель
        пишет прежнее время в 24-часовом виде («в 9 вечера» → «21:00»).
        """
        return TimeExpression(clock=self.target_time)

    @property
    def renamed_to(self) -> str:
        """Новое название при переименовании (модель иногда кладёт его в `title`)."""
        return self.new_title or self.title

    @property
    def time_expression(self) -> TimeExpression:
        """Названное время.

        Часть суток, которую модель написала в `time` вместо `day_part` («"time": "morning"»
        на «в пятницу утром»), считается частью суток.
        """
        misplaced = DAY_PART_WORDS.get(self.time.strip().lower())
        if misplaced is not None and self.day_part is DayPart.NONE:
            return TimeExpression(day_part=misplaced, in_minutes=self.in_minutes)
        return TimeExpression(clock=self.time, day_part=self.day_part, in_minutes=self.in_minutes)


def _enum(values: type[StrEnum], description: str) -> dict[str, Any]:
    return {
        "type": "string",
        "enum": [member.value for member in values],
        "description": description,
    }


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _integer(description: str, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": 0, "maximum": maximum, "description": description}


MAX_CHOICE = 20
MINUTES_IN_DAY = 24 * 60
MINUTES_IN_WEEK = 7 * MINUTES_IN_DAY

_PROPERTIES: dict[str, dict[str, Any]] = {
    "action": _enum(Action, "Что хочет пользователь"),
    "event_type": _enum(EventTypeName, "Тип записи; none — не назван"),
    "query": _string("Что искать или какую запись менять"),
    "about_last": {"type": "boolean", "description": "Запись названа местоимением: её, эту"},
    "target_date": _enum(DateKind, "Для reschedule: день, где запись стоит сейчас, если назван"),
    "target_time": _string("Для reschedule: время, где запись стоит сейчас, ЧЧ:ММ, если названо"),
    "title": _string("Название создаваемой записи или ответ-название"),
    "new_title": _string("Для rename: новое название"),
    "date": _enum(DateKind, "Как назван день или период (для reschedule — новый день)"),
    "date_value": _string("Для date=exact — ДД.ММ, для date=in_days — число дней"),
    "time": _string("Время как названо, Ч:ММ (для reschedule — новое время)"),
    "day_part": _enum(DayPart, "Часть суток, если сказана"),
    "in_minutes": _integer("«Через N минут/часов» в минутах", MINUTES_IN_WEEK),
    "duration_minutes": _integer(
        "Длительность встречи в минутах (для reschedule — новая)", MINUTES_IN_DAY
    ),
    "time_scope": _enum(TimeScope, "Для поиска: past — была, future — будет, иначе any"),
    "status": _enum(StatusName, "Фильтр выполненности; none — не назван"),
    "choice": _integer("Для choose: номер варианта с 1", MAX_CHOICE),
    "rest": _string("Остальные команды реплики, кроме разобранной первой, словами пользователя"),
}
"""Порядок полей важен: GigaChat в режиме strict пишет поля только в порядке схемы.

Поэтому сначала идёт то, что пользователь говорит раньше по смыслу: какая запись
(`query`, `target_date`, `target_time`), потом что с ней сделать (`new_title`, новые `date`
и `time`). При обратном порядке модель, написав `query`, уже не возвращалась к `new_title`.
`rest` — последним: остальные команды реплики модель выписывает, разобрав первую.
"""

REQUIRED_FIELD = "action"

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _PROPERTIES,
    "required": [REQUIRED_FIELD],
    "additionalProperties": False,
}
"""JSON-схема ответа модели (`response_format: json_schema`, `strict: true`)."""
