"""Изменение найденной записи: перенос, переименование, отметка о выполнении, удаление.

Перенос, переименование и отметка выполняются сразу и возвращают кнопку отмены;
удаление всегда переспрашивается (Q33). Перенос встречи сохраняет её длительность
и проверяет пересечение с другими встречами.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from types import MappingProxyType

from app.core.dialog import phrases
from app.core.dialog.conflicts import ConflictFinder, meeting_duration
from app.core.dialog.models import (
    Outcome,
    PendingQuestion,
    PendingStep,
    Reply,
    Turn,
    UndoTicket,
)
from app.core.dialog.rules import (
    reschedule_question,
    rescheduled_schedule,
    resolved_when,
    tidy_title,
)
from app.core.dialog.undo import RestoreDeleted, RevertChanges, StoredOperation, UndoLog
from app.core.enums import EventStatus, EventType, PendingExpectation, ReplyKind
from app.core.events import EventCard, EventChanges, EventEditor
from app.core.queries import MeetingSlot
from app.core.schedule import Schedule
from app.nlu.interfaces import Action, Intent, When

ChangeHandler = Callable[[Turn, Intent, EventCard], Awaitable[Outcome]]


class ChangeFlow:
    """Команды над одной уже найденной записью."""

    def __init__(self, editor: EventEditor, conflicts: ConflictFinder, undo: UndoLog) -> None:
        self._editor = editor
        self._conflicts = conflicts
        self._undo = undo
        self._handlers: Mapping[Action, ChangeHandler] = MappingProxyType(
            {
                Action.RESCHEDULE: self._reschedule,
                Action.RENAME: self._rename,
                Action.COMPLETE: self._complete,
                Action.DELETE: self._ask_delete,
            }
        )
        self._confirmed: Mapping[Action, ChangeHandler] = MappingProxyType(
            {
                Action.RESCHEDULE: self._reschedule_confirmed,
                Action.DELETE: self._delete_confirmed,
            }
        )

    async def apply(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        """Выполняет команду `intent.action` над записью `target`."""
        return await self._handlers[intent.action](turn, intent, target)

    async def confirm(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        """Выполняет команду, которую пользователь подтвердил («да», «всё равно перенеси»)."""
        return await self._confirmed[intent.action](turn, intent, target)

    async def _reschedule(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        question = reschedule_question(target, intent.when, turn.today)
        if question is not None:
            return Outcome.clarify(PendingStep(question, intent, target_id=target.id))
        schedule = rescheduled_schedule(target, intent.when or When(), turn.now)
        conflicts = await self._meeting_conflicts(turn, target, schedule)
        if conflicts:
            resolved = replace(intent, when=resolved_when(schedule))
            return _confirm_move_despite_conflicts(resolved, target, conflicts)
        return await self._move(turn, target, schedule)

    async def _reschedule_confirmed(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        schedule = rescheduled_schedule(target, intent.when or When(), turn.now)
        return await self._move(turn, target, schedule)

    async def _meeting_conflicts(
        self, turn: Turn, target: EventCard, schedule: Schedule
    ) -> list[EventCard]:
        if target.type is not EventType.MEETING or schedule.starts_at is None:
            return []
        slot = MeetingSlot(
            profile_id=turn.profile_id,
            starts_at=schedule.starts_at,
            ends_at=schedule.starts_at + meeting_duration(target),
            ignored_event_id=target.id,
        )
        return await self._conflicts.find(slot)

    async def _move(self, turn: Turn, target: EventCard, schedule: Schedule) -> Outcome:
        changes = EventChanges(starts_at=schedule.starts_at, has_time=schedule.has_time)
        card, ticket = await self._change(turn, target, changes)
        reply = Reply(
            ReplyKind.CONFIRMATION,
            phrases.rescheduled(card, turn.today),
            events=(card,),
            undo=ticket,
        )
        return Outcome(reply, focus=(card.id,))

    async def _rename(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        title = tidy_title(intent.title)
        if title is None:
            question = PendingQuestion(PendingExpectation.TITLE, phrases.rename_question(target))
            return Outcome.clarify(PendingStep(question, intent, target_id=target.id))
        card, ticket = await self._change(turn, target, EventChanges(title=title))
        reply = Reply(
            ReplyKind.CONFIRMATION,
            phrases.renamed(target.title, card),
            events=(card,),
            undo=ticket,
        )
        return Outcome(reply, focus=(card.id,))

    async def _complete(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        if target.status is EventStatus.DONE:
            reply = Reply(ReplyKind.INFO, phrases.already_completed(target), events=(target,))
            return Outcome(reply, focus=(target.id,))
        card, ticket = await self._change(turn, target, EventChanges(status=EventStatus.DONE))
        reply = Reply(ReplyKind.CONFIRMATION, phrases.completed(card), events=(card,), undo=ticket)
        return Outcome(reply, focus=(card.id,))

    async def _ask_delete(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        question = PendingQuestion(
            PendingExpectation.CONFIRM, phrases.delete_question(target, turn.today)
        )
        reply = Reply(
            ReplyKind.CONFIRM_REQUEST, question.question, events=(target,), pending=question
        )
        step = PendingStep(question, replace(intent, action=Action.DELETE), target_id=target.id)
        return Outcome(reply, pending=step, focus=(target.id,))

    async def _delete_confirmed(self, turn: Turn, intent: Intent, target: EventCard) -> Outcome:
        snapshot = await self._editor.delete(turn.profile_id, target.id)
        ticket = await self._record(turn, RestoreDeleted(snapshot))
        reply = Reply(
            ReplyKind.CONFIRMATION, phrases.deleted(target), events=(target,), undo=ticket
        )
        return Outcome(reply)

    async def _change(
        self, turn: Turn, target: EventCard, changes: EventChanges
    ) -> tuple[EventCard, UndoTicket]:
        """Меняет запись и запоминает, как вернуть её прежние поля."""
        before = await self._editor.snapshot(turn.profile_id, target.id)
        card = await self._editor.update(turn.profile_id, target.id, changes)
        return card, await self._record(turn, RevertChanges(before))

    async def _record(self, turn: Turn, operation: StoredOperation) -> UndoTicket:
        return await self._undo.record(turn.profile_id, operation, turn.now)


def _confirm_move_despite_conflicts(
    intent: Intent, target: EventCard, conflicts: list[EventCard]
) -> Outcome:
    question = PendingQuestion(
        PendingExpectation.CONFIRM, phrases.conflict_question(conflicts, phrases.MOVE_ANYWAY)
    )
    reply = Reply(
        ReplyKind.CONFIRM_REQUEST,
        question.question,
        events=(target,),
        conflicts=conflicts,
        pending=question,
    )
    return Outcome(reply, pending=PendingStep(question, intent, target_id=target.id))
