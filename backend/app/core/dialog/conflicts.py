"""Пересечение встреч: новая или перенесённая встреча не должна молча наложиться на другую."""

from datetime import timedelta

from app.core.events import EventCard
from app.core.queries import MeetingSlot
from app.core.schedule import DEFAULT_MEETING_DURATION
from app.storage.database import UnitOfWork


class ConflictFinder:
    """Ищет открытые встречи профиля, которые пересекаются с заданным временем."""

    def __init__(self, storage: UnitOfWork) -> None:
        self._storage = storage

    async def find(self, slot: MeetingSlot) -> list[EventCard]:
        """Встречи, пересекающиеся со `slot`, по времени начала."""
        records = await self._storage.events.find_overlapping_meetings(slot)
        return [EventCard.from_record(record) for record in records]


def meeting_duration(card: EventCard) -> timedelta:
    """Длительность встречи; без конца — длительность по умолчанию."""
    if card.starts_at is None or card.ends_at is None:
        return DEFAULT_MEETING_DURATION
    return card.ends_at - card.starts_at
