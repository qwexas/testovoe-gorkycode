"""отмена изменений через обратную операцию в `undo_actions` (Q33)

Сервер даёт на отмену 30 с, интерфейс показывает кнопку 10 с.
Оставшееся время — запас на сеть и голосовую команду.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter

from app.core.dialog import phrases
from app.core.dialog.models import Reply, UndoTicket
from app.core.enums import ReplyKind
from app.core.errors import EventNotFoundError, UndoUnavailableError
from app.core.events import EventEditor, EventSnapshot
from app.core.tokens import new_action_id
from app.storage.database import UnitOfWork
from app.storage.models import UndoActionRecord

UNDO_WINDOW = timedelta(seconds=30)


class UndoOperation(Protocol):
    """обратная операция к действию над записью."""

    async def revert(self, editor: EventEditor, profile_id: UUID, today: date) -> Reply:
        """откатывает действие и описывает результат.

        Raises:
            EventNotFoundError: Записи, которую нужно вернуть, больше нет.
        """
        ...


@dataclass(frozen=True, slots=True)
class RemoveCreated:
    """отмена создания: удалить созданную запись."""

    event_id: int
    operation: Literal["remove_created"] = "remove_created"

    async def revert(self, editor: EventEditor, profile_id: UUID, today: date) -> Reply:
        """удаляет созданную запись."""
        snapshot = await editor.delete(profile_id, self.event_id)
        return Reply(ReplyKind.CONFIRMATION, phrases.undo_removed(snapshot.title))


@dataclass(frozen=True, slots=True)
class RevertChanges:
    """отмена переноса, переименования или отметки: вернуть прежние поля записи."""

    previous: EventSnapshot
    operation: Literal["revert_changes"] = "revert_changes"

    async def revert(self, editor: EventEditor, profile_id: UUID, today: date) -> Reply:
        """возвращает записи поля из снимка."""
        card = await editor.update(profile_id, self.previous.id, self.previous.as_changes())
        return Reply(ReplyKind.CONFIRMATION, phrases.undo_reverted(card, today), events=(card,))


@dataclass(frozen=True, slots=True)
class RestoreDeleted:
    """отмена удаления: вернуть запись с прежним `id`."""

    snapshot: EventSnapshot
    operation: Literal["restore_deleted"] = "restore_deleted"

    async def revert(self, editor: EventEditor, profile_id: UUID, today: date) -> Reply:
        """возвращает удалённую запись."""
        card = await editor.restore(profile_id, self.snapshot)
        return Reply(ReplyKind.CONFIRMATION, phrases.undo_restored(card), events=(card,))


StoredOperation = Annotated[
    RemoveCreated | RevertChanges | RestoreDeleted, Field(discriminator="operation")
]
_OPERATION: TypeAdapter[StoredOperation] = TypeAdapter(StoredOperation)


class UndoLog:
    """журнал отменяемых действий профиля в транзакции вызывающего сценария."""

    def __init__(self, storage: UnitOfWork, editor: EventEditor) -> None:
        self._storage = storage
        self._editor = editor

    async def record(
        self, profile_id: UUID, operation: StoredOperation, now: datetime
    ) -> UndoTicket:
        """запоминает обратную операцию; заодно забывает действия с прошедшим сроком."""
        await self._storage.undo_actions.delete_expired(profile_id, now)
        action = UndoActionRecord(
            action_id=new_action_id(),
            profile_id=profile_id,
            payload=_OPERATION.dump_python(operation, mode="json"),
            expires_at=now + UNDO_WINDOW,
        )
        await self._storage.undo_actions.add(action)
        return UndoTicket(action_id=action.action_id, expires_at=action.expires_at)

    async def undo(self, profile_id: UUID, action_id: str, now: datetime) -> Reply:
        """отменяет действие по кнопке.

        Raises:
            UndoUnavailableError: Действия нет, оно чужое, уже отменено или срок прошёл.
        """
        action = await self._storage.undo_actions.get(profile_id, action_id)
        if action is None or action.expires_at <= now:
            raise UndoUnavailableError()
        return await self._revert(action, now)

    async def undo_latest(self, profile_id: UUID, now: datetime) -> Reply:
        """отменяет последнее действие профиля по голосовой команде «отмени»."""
        action = await self._storage.undo_actions.latest(profile_id)
        if action is None:
            return Reply(ReplyKind.INFO, phrases.NOTHING_TO_UNDO)
        if action.expires_at <= now:
            return Reply(ReplyKind.INFO, phrases.UNDO_EXPIRED)
        try:
            return await self._revert(action, now)
        except UndoUnavailableError:
            return Reply(ReplyKind.INFO, phrases.UNDO_EXPIRED)

    async def _revert(self, action: UndoActionRecord, now: datetime) -> Reply:
        operation: UndoOperation = _OPERATION.validate_python(action.payload)
        await self._storage.undo_actions.delete(action.profile_id, action.action_id)
        try:
            return await operation.revert(self._editor, action.profile_id, now.date())
        except EventNotFoundError as error:
            raise UndoUnavailableError() from error
