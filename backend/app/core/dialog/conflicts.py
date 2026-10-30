"""столкновения при создании и переносе: новая запись не должна молча лечь поверх другой.

- Пересечение встреч: новая или перенесённая встреча занимает время открытой встречи.
- Дубль: открытая запись того же типа с тем же названием (без учёта регистра, «ё»,
  пробелов и знаков) на то же время уже есть — например, фразу повторили дважды.
"""

import re
from datetime import timedelta
from uuid import UUID

from app.core.events import EventCard, EventDraft
from app.core.queries import MeetingSlot, SameMoment
from app.core.schedule import DEFAULT_MEETING_DURATION
from app.storage.database import UnitOfWork

_WORD = re.compile(r"\w+")


class ConflictFinder:
    """ищет открытые записи профиля, с которыми столкнётся новая или перенесённая."""

    def __init__(self, storage: UnitOfWork) -> None:
        self._storage = storage

    async def find(self, slot: MeetingSlot) -> list[EventCard]:
        """встречи, пересекающиеся со `slot`, по времени начала."""
        records = await self._storage.events.find_overlapping_meetings(slot)
        return [EventCard.from_record(record) for record in records]

    async def duplicate_of(self, profile_id: UUID, draft: EventDraft) -> EventCard | None:
        """открытая запись, которую повторяет `draft`: тот же тип, название и время."""
        moment = SameMoment(profile_id, draft.type, draft.starts_at)
        records = await self._storage.events.list_at_moment(moment)
        title = normalized_title(draft.title)
        same = (
            record
            for record in records
            if record.has_time == draft.has_time and normalized_title(record.title) == title
        )
        record = next(same, None)
        return None if record is None else EventCard.from_record(record)


def normalized_title(title: str) -> str:
    """название для сравнения: слова в нижнем регистре, «ё» как «е», без знаков."""
    return " ".join(_WORD.findall(title.casefold().replace("ё", "е")))


def meeting_duration(card: EventCard) -> timedelta:
    """длительность встречи; без конца — длительность по умолчанию."""
    if card.starts_at is None or card.ends_at is None:
        return DEFAULT_MEETING_DURATION
    return card.ends_at - card.starts_at
