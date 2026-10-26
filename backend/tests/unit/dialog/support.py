"""Опора тестов диалога: фейковые хранилища, поиск без модели и заготовки `Intent`.

`FakeIntentParser` играет роль ИИ-части: тест говорит, во что разбирается реплика,
а проверяется только бизнес-логика диалога.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.core.dialog.models import AssistantAnswer, Reply
from app.core.dialog.service import DialogDependencies, DialogService, MessageThrottle
from app.core.enums import EventSource, EventStatus, EventType, MessageSource
from app.core.events import EventCard
from app.core.queries import EventFilter, MeetingSlot
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.schedule import DEFAULT_MEETING_DURATION, MOSCOW
from app.core.search import SearchService
from app.nlu.interfaces import (
    Action,
    DialogContext,
    Intent,
    Period,
    TargetRef,
    When,
)
from app.search.interfaces import RankedResult, SearchCandidate
from app.search.placeholders import HashingEmbedder
from app.storage.models import (
    ChatMessageRecord,
    DialogStateRecord,
    EventRecord,
    UndoActionRecord,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=MOSCOW)
"""Понедельник, 26 октября 2026, полдень по Москве."""
TODAY = NOW.date()
TOMORROW = date(2026, 10, 27)
THURSDAY = date(2026, 10, 29)
FRIDAY = date(2026, 10, 30)
SUNDAY = date(2026, 11, 1)
NEXT_MONDAY = date(2026, 11, 2)
WORD = re.compile(r"[а-яёa-z0-9]+")
STEM_LENGTH = 4
MIN_WORD_LENGTH = 3


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """Момент по Москве."""
    return datetime.combine(day, time(hour, minute), tzinfo=MOSCOW)


def day_period(day: date, label: str) -> Period:
    """Период — один день."""
    start = datetime.combine(day, time.min, tzinfo=MOSCOW)
    return Period(start=start, end=start + timedelta(days=1), label=label)


def card(event_type: EventType, title: str, starts_at: datetime | None, **fields: Any) -> EventCard:
    """Карточка записи для проверок без хранилища."""
    values: dict[str, Any] = {
        "id": 1,
        "type": event_type,
        "title": title,
        "starts_at": starts_at,
        "has_time": starts_at is not None,
        "ends_at": None,
        "status": EventStatus.OPEN,
        "source": EventSource.USER,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return EventCard(**(values | fields))


# --- Фейковые хранилища -----------------------------------------------------------------------


class FakeEventRepository:
    """Записи в памяти с изоляцией по профилю, фильтрами и пересечением встреч."""

    def __init__(self) -> None:
        self.records: dict[int, EventRecord] = {}
        self._next_id = 1

    async def add(self, event: EventRecord) -> None:
        if event.id is None:
            event.id = self._next_id
        self._next_id = max(self._next_id, event.id + 1)
        event.status = event.status or EventStatus.OPEN
        event.source = event.source or EventSource.USER
        event.created_at = event.created_at or NOW
        event.updated_at = NOW
        self.records[event.id] = event

    async def get(self, profile_id: UUID, event_id: int) -> EventRecord | None:
        event = self.records.get(event_id)
        return event if event is not None and event.profile_id == profile_id else None

    async def get_many(self, profile_id: UUID, event_ids: Sequence[int]) -> list[EventRecord]:
        found = [await self.get(profile_id, event_id) for event_id in event_ids]
        return [event for event in found if event is not None]

    async def delete(self, profile_id: UUID, event_id: int) -> bool:
        if await self.get(profile_id, event_id) is None:
            return False
        del self.records[event_id]
        return True

    async def list_matching(self, criteria: EventFilter, limit: int) -> list[EventRecord]:
        matching = [event for event in self.records.values() if _matches(event, criteria)]
        matching.sort(key=lambda e: (e.starts_at is None, e.starts_at or NOW, e.id))
        return matching[:limit]

    async def find_candidates(
        self, criteria: EventFilter, query_vector: Sequence[float], query_lemmas: Sequence[str]
    ) -> list[SearchCandidate]:
        return [
            SearchCandidate(
                event_id=event.id,
                lemmas=event.lemmas or [],
                similarity=0.5,
                event_type=event.type,
            )
            for event in self.records.values()
            if _matches(event, criteria)
        ]

    async def find_overlapping_meetings(self, slot: MeetingSlot) -> list[EventRecord]:
        overlapping = [
            event
            for event in self.records.values()
            if event.profile_id == slot.profile_id
            and event.type is EventType.MEETING
            and event.status is EventStatus.OPEN
            and event.id != slot.ignored_event_id
            and event.starts_at is not None
            and event.starts_at < slot.ends_at
            and (event.ends_at or event.starts_at + DEFAULT_MEETING_DURATION) > slot.starts_at
        ]
        return sorted(overlapping, key=lambda e: e.starts_at or NOW)


def _matches(event: EventRecord, criteria: EventFilter) -> bool:
    if event.profile_id != criteria.profile_id:
        return False
    if criteria.event_type is not None and event.type is not criteria.event_type:
        return False
    if criteria.status is not None and event.status is not criteria.status:
        return False
    if criteria.period_start is None and criteria.period_end is None:
        return True
    if event.starts_at is None:
        return False
    after_start = criteria.period_start is None or event.starts_at >= criteria.period_start
    before_end = criteria.period_end is None or event.starts_at < criteria.period_end
    return after_start and before_end


class FakeMessageRepository:
    def __init__(self) -> None:
        self.messages: list[ChatMessageRecord] = []

    async def add(self, message: ChatMessageRecord) -> None:
        message.id = len(self.messages) + 1
        message.created_at = NOW
        self.messages.append(message)

    async def list_before(
        self, profile_id: UUID, before_id: int | None, limit: int
    ) -> list[ChatMessageRecord]:
        owned = [
            message
            for message in self.messages
            if message.profile_id == profile_id and (before_id is None or message.id < before_id)
        ]
        return owned[-limit:]


class FakeDialogStateRepository:
    def __init__(self) -> None:
        self.states: dict[UUID, DialogStateRecord] = {}

    async def get(self, profile_id: UUID) -> DialogStateRecord | None:
        return self.states.get(profile_id)

    async def save(self, state: DialogStateRecord) -> None:
        self.states[state.profile_id] = state


class FakeUndoRepository:
    def __init__(self) -> None:
        self.actions: dict[str, UndoActionRecord] = {}

    async def add(self, action: UndoActionRecord) -> None:
        self.actions[action.action_id] = action

    async def get(self, profile_id: UUID, action_id: str) -> UndoActionRecord | None:
        action = self.actions.get(action_id)
        return action if action is not None and action.profile_id == profile_id else None

    async def latest(self, profile_id: UUID) -> UndoActionRecord | None:
        owned = [a for a in self.actions.values() if a.profile_id == profile_id]
        return max(owned, key=lambda a: a.expires_at, default=None)

    async def delete(self, profile_id: UUID, action_id: str) -> None:
        if await self.get(profile_id, action_id) is not None:
            del self.actions[action_id]

    async def delete_expired(self, profile_id: UUID, moment: datetime) -> None:
        expired = [
            a.action_id
            for a in self.actions.values()
            if a.profile_id == profile_id and a.expires_at <= moment
        ]
        for action_id in expired:
            del self.actions[action_id]


class FakeStorage:
    def __init__(self) -> None:
        self.events = FakeEventRepository()
        self.messages = FakeMessageRepository()
        self.dialog_states = FakeDialogStateRepository()
        self.undo_actions = FakeUndoRepository()
        self.commits = 0

    async def flush(self) -> None:
        """В памяти отправлять нечего."""

    async def commit(self) -> None:
        self.commits += 1


# --- Поиск без модели -------------------------------------------------------------------------


class PrefixLemmatizer:
    """«Иваном» и «Иван» → «иван»: первые четыре буквы слов длиннее двух букв."""

    def lemmas(self, text: str) -> list[str]:
        words = (word for word in WORD.findall(text.lower()) if len(word) >= MIN_WORD_LENGTH)
        return list(dict.fromkeys(word[:STEM_LENGTH] for word in words))


class ContainsAllRanker:
    """Запись подходит, если в ней есть все леммы запроса; тип из разбора — небольшой бонус."""

    TYPE_BONUS = 0.5

    def __init__(self) -> None:
        self.preferred_types: list[EventType | None] = []

    def rank(
        self,
        query_lemmas: Sequence[str],
        candidates: Sequence[SearchCandidate],
        *,
        limit: int,
        preferred_type: EventType | None = None,
    ) -> list[RankedResult]:
        self.preferred_types.append(preferred_type)
        wanted = set(query_lemmas)
        relevant = [
            RankedResult(
                event_id=c.event_id,
                score=1.0 + (self.TYPE_BONUS if c.event_type is preferred_type else 0.0),
            )
            for c in candidates
            if wanted and wanted <= set(c.lemmas)
        ]
        relevant.sort(key=lambda result: (-result.score, result.event_id))
        return relevant[:limit]


# --- Парсер и часы ----------------------------------------------------------------------------


class FakeIntentParser:
    """Разбор по сценарию теста: реплика → заготовленный `Intent` (или ошибка)."""

    def __init__(self) -> None:
        self.script: dict[str, Intent | Exception] = {}
        self.contexts: list[DialogContext] = []

    async def parse(self, text: str, context: DialogContext) -> Intent:
        self.contexts.append(context)
        result = self.script[text]
        if isinstance(result, Exception):
            raise result
        return result


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


# --- Сборка диалога ----------------------------------------------------------------------------


@dataclass
class DialogHarness:
    """Диалог одного профиля: реплика → ответ, плюс доступ к хранилищу."""

    storage: FakeStorage
    parser: FakeIntentParser
    clock: FakeClock
    ranker: ContainsAllRanker
    throttle: MessageThrottle
    profile_id: UUID = field(default_factory=uuid4)

    @property
    def service(self) -> DialogService:
        fake_storage: Any = self.storage
        search = SearchService(HashingEmbedder(), PrefixLemmatizer(), self.ranker)
        dependencies = DialogDependencies(
            parser=self.parser, search=search, throttle=self.throttle, clock=self.clock
        )
        return DialogService(fake_storage, dependencies)

    async def say(self, intent: Intent) -> Reply:
        """Пользователь произносит `intent.text`; парсер разбирает его в `intent`."""
        return (await self.answer(intent)).reply

    async def answer(
        self, intent: Intent, source: MessageSource = MessageSource.TEXT
    ) -> AssistantAnswer:
        self.parser.script[intent.text] = intent
        return await self.service.handle(self.profile_id, intent.text, source)

    async def add_event(
        self,
        event_type: EventType,
        title: str,
        starts_at: datetime | None = None,
        **fields: Any,
    ) -> EventCard:
        """Запись профиля, как будто созданная раньше (например, история из CSV)."""
        has_time = fields.pop("has_time", starts_at is not None)
        ends_at = fields.pop("ends_at", None)
        if event_type is EventType.MEETING and ends_at is None and starts_at is not None:
            ends_at = starts_at + DEFAULT_MEETING_DURATION
        record = EventRecord(
            profile_id=fields.pop("profile_id", self.profile_id),
            type=event_type,
            title=title,
            starts_at=starts_at,
            has_time=has_time,
            ends_at=ends_at,
            lemmas=PrefixLemmatizer().lemmas(title),
            **fields,
        )
        await self.storage.events.add(record)
        return EventCard.from_record(record)

    def event(self, event_id: int) -> EventRecord | None:
        return self.storage.events.records.get(event_id)

    @property
    def state(self) -> DialogStateRecord | None:
        return self.storage.dialog_states.states.get(self.profile_id)


def new_dialog() -> DialogHarness:
    """Пустой диалог нового профиля с почти безлимитной частотой реплик."""
    limiter = SlidingWindowRateLimiter(max_hits=1000, window_seconds=60)
    return DialogHarness(
        storage=FakeStorage(),
        parser=FakeIntentParser(),
        clock=FakeClock(),
        ranker=ContainsAllRanker(),
        throttle=MessageThrottle(limiter),
    )


# --- Заготовки разбора -----------------------------------------------------------------------


def create(
    text: str, event_type: EventType | None, title: str | None, **when_fields: Any
) -> Intent:
    """CREATE: `when_fields` — поля `When` (date, time, week_of) и duration_minutes."""
    duration = when_fields.pop("duration_minutes", None)
    when = When(**when_fields) if when_fields else None
    return Intent(
        Action.CREATE,
        text,
        event_type=event_type,
        title=title,
        when=when,
        duration_minutes=duration,
    )


def answer(text: str, **fields: Any) -> Intent:
    """ANSWER: `title` и поля `When`."""
    title = fields.pop("title", None)
    return Intent(Action.ANSWER, text, title=title, when=When(**fields) if fields else None)


def listing(text: str, **fields: Any) -> Intent:
    return Intent(Action.LIST, text, **fields)


def search(text: str, query: str, **fields: Any) -> Intent:
    return Intent(Action.SEARCH, text, query=query, **fields)


def change(action: Action, text: str, **fields: Any) -> Intent:
    """RESCHEDULE / RENAME / COMPLETE / DELETE: `target` — ссылка на запись."""
    return Intent(action, text, **fields)


def it() -> TargetRef:
    """«её», «эту встречу»."""
    return TargetRef(last=True)


def about(query: str, **fields: Any) -> TargetRef:
    """«встречу с Иваном»."""
    return TargetRef(query=query, **fields)


def choose(text: str, index: int | None = None, title: str | None = None) -> Intent:
    return Intent(Action.CHOOSE, text, choice_index=index, title=title)


def simple(action: Action, text: str) -> Intent:
    """CONFIRM, DENY, UNDO, SMALLTALK, UNKNOWN."""
    return Intent(action, text)
