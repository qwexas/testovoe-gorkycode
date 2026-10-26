"""Критерии выборки записей — общий язык бизнес-логики и хранилища.

Модуль зависит только от словаря `app.core.enums`, поэтому его импортирует и слой
`storage`, не создавая циклов.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.enums import EventStatus, EventType


@dataclass(frozen=True, slots=True)
class EventFilter:
    """Какие записи профиля выбрать.

    Период — полуинтервал `[period_start, period_end)` по началу записи; записи
    без даты (задачи «без срока») в выборку с периодом не попадают. `event_types` —
    записи любого из этих типов; `None` — любого типа.
    """

    profile_id: UUID
    period_start: datetime | None = None
    period_end: datetime | None = None
    event_types: frozenset[EventType] | None = None
    status: EventStatus | None = None


@dataclass(frozen=True, slots=True)
class MeetingSlot:
    """Время встречи `[starts_at, ends_at)`, с которым не должны пересекаться другие встречи.

    `ignored_event_id` — сама переносимая встреча: с собой она не конфликтует.
    """

    profile_id: UUID
    starts_at: datetime
    ends_at: datetime
    ignored_event_id: int | None = None
