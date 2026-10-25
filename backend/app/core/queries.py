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
    без даты (задачи «без срока») в выборку с периодом не попадают.
    """

    profile_id: UUID
    period_start: datetime | None = None
    period_end: datetime | None = None
    event_type: EventType | None = None
    status: EventStatus | None = None
