"""Модели диалога: ответ ассистента, отложенный шаг, итог обработки реплики.

Слой `core` не знает про HTTP: здесь доменные структуры, а схемы контракта —
в `app.api.schemas.dialog`. JSON ответа для истории и API собирает `app.core.dialog.payloads`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Self
from uuid import UUID

from app.core.enums import MessageRole, PendingExpectation, ReplyKind
from app.core.events import EventCard
from app.nlu.interfaces import Intent, Period

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """Вопрос ассистента и чего он ждёт в ответ."""

    expects: PendingExpectation
    question: str


@dataclass(frozen=True, slots=True)
class UndoTicket:
    """Действие можно отменить до `expires_at`."""

    action_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Reply:
    """Что ассистент говорит и показывает в ответ на реплику."""

    kind: ReplyKind
    text: str
    events: Sequence[EventCard] = ()
    period: Period | None = None
    choices: Sequence[EventCard] = ()
    """Варианты выбора по порядку: номер варианта — позиция с 1."""
    conflicts: Sequence[EventCard] = ()
    pending: PendingQuestion | None = None
    undo: UndoTicket | None = None


@dataclass(frozen=True, slots=True)
class PendingStep:
    """Незавершённое действие: ассистент задал вопрос и ждёт ответа.

    `intent` — что пользователь хотел сделать (уже дополненное прежними ответами);
    `target_id` — выбранная запись для изменения; `option_ids` — варианты выбора по порядку.
    """

    question: PendingQuestion
    intent: Intent
    target_id: int | None = None
    option_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    """Итог обработки реплики: ответ, следующий отложенный шаг и записи для фокуса.

    `focus` — записи, которые становятся первыми в фокусе диалога (созданная, найденная…).
    `peer_focus` — это равноправные записи ответа-списка (список за период, найденные,
    варианты выбора): «её» после такого ответа неоднозначно и переспрашивается.
    """

    reply: Reply
    pending: PendingStep | None = None
    focus: tuple[int, ...] = ()
    peer_focus: bool = False

    @property
    def focus_peers(self) -> int:
        """Сколько первых записей `focus` равноправны: все из ответа-списка, иначе первая."""
        return len(self.focus) if self.peer_focus else min(len(self.focus), 1)

    @classmethod
    def say(cls, text: str) -> Self:
        """Ответ-сообщение (`info`) без записей и без вопроса."""
        return cls(Reply(ReplyKind.INFO, text))

    @classmethod
    def clarify(cls, step: PendingStep) -> Self:
        """Уточняющий вопрос (Q30): чего не хватает для действия."""
        return cls(
            Reply(ReplyKind.CLARIFICATION, step.question.question, pending=step.question),
            pending=step,
        )


@dataclass(frozen=True, slots=True)
class Turn:
    """Обстановка, в которой обрабатывается реплика."""

    profile_id: UUID
    now: datetime
    """Текущий момент по Москве."""
    pending: PendingStep | None = None
    focus: Sequence[EventCard] = field(default_factory=tuple)
    """Записи в фокусе, последняя упомянутая — первой."""
    peers: Sequence[EventCard] = field(default_factory=tuple)
    """Записи последнего ответа-списка, если их больше одной: для «её» нужно переспросить."""

    @property
    def today(self) -> date:
        """Сегодняшний день по Москве."""
        return self.now.date()


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """Сохранённый ответ ассистента: реплика в истории с полным ответом."""

    message_id: int
    reply: Reply
    recognized_text: str | None = None


@dataclass(frozen=True, slots=True)
class DialogEntry:
    """Реплика истории диалога; у ответов ассистента — полный ответ в формате контракта."""

    id: int
    role: MessageRole
    text: str
    created_at: datetime
    reply: JsonObject | None
