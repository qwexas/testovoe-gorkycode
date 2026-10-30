"""схемы записей: задач, напоминаний и встреч."""

from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints

from app.api.schemas.base import RequestModel, ResponseModel
from app.core.enums import EventSource, EventStatus, EventType

TITLE_MAX_LENGTH = 500

EventTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH)
]


class Event(ResponseModel):
    """Задача, напоминание или встреча."""

    id: int
    type: EventType
    title: str = Field(description="Название / текст")
    starts_at: datetime | None = Field(
        description="Срок задачи, время напоминания, начало встречи; `null` — задача без срока"
    )
    has_time: bool = Field(
        description="`false` — указан только день: время в `starts_at` = 00:00 и не показывается"
    )
    ends_at: datetime | None = Field(
        description="Конец встречи (по умолчанию начало + 60 мин); у задач и напоминаний `null`"
    )
    status: EventStatus
    source: EventSource = Field(description="`import` — история из CSV")
    created_at: datetime
    updated_at: datetime


class EventCreate(RequestModel):
    """Создание записи из интерфейса."""

    type: EventType
    title: EventTitle
    starts_at: AwareDatetime | None = None
    has_time: bool = Field(default=True, description="`false` — у записи только дата, без времени")
    ends_at: AwareDatetime | None = None


class EventUpdate(RequestModel):
    """Изменение записи: передаются только меняющиеся поля."""

    title: EventTitle | None = None
    starts_at: AwareDatetime | None = None
    has_time: bool | None = None
    ends_at: AwareDatetime | None = None
    status: EventStatus | None = None


class EventsResponse(ResponseModel):
    """Список записей."""

    events: list[Event]
