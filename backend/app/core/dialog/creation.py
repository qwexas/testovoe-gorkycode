"""Создание задач, напоминаний и встреч: уточнение (Q30), дубль, конфликт встреч, отмена."""

from dataclasses import replace

from app.core.dialog import phrases
from app.core.dialog.conflicts import ConflictFinder
from app.core.dialog.models import Outcome, PendingQuestion, PendingStep, Reply, Turn
from app.core.dialog.rules import created_type, creation_draft, creation_question, tidy_title
from app.core.dialog.undo import RemoveCreated, UndoLog
from app.core.enums import EventType, PendingExpectation, ReplyKind
from app.core.events import EventCard, EventDraft, EventEditor
from app.core.queries import MeetingSlot
from app.nlu.interfaces import Intent


class CreationFlow:
    """Команда «создай»: спросить недостающее, предупредить о пересечении, создать."""

    def __init__(self, editor: EventEditor, conflicts: ConflictFinder, undo: UndoLog) -> None:
        self._editor = editor
        self._conflicts = conflicts
        self._undo = undo

    async def start(self, turn: Turn, intent: Intent) -> Outcome:
        """Создаёт запись или задаёт уточняющий вопрос.

        Отложенный шаг хранит разбор с уже определённым типом: ответ на вопрос
        («в 15») дополняет именно его.
        """
        typed = replace(intent, event_type=created_type(intent), title=tidy_title(intent.title))
        question = creation_question(typed, turn.today)
        if question is not None:
            return Outcome.clarify(PendingStep(question, typed))
        draft = creation_draft(typed, turn.now)
        duplicate = await self._conflicts.duplicate_of(turn.profile_id, draft)
        if duplicate is not None:
            return _confirm_duplicate(typed, duplicate, turn)
        conflicts = await self._meeting_conflicts(turn, draft)
        if conflicts:
            return _confirm_despite_conflicts(typed, conflicts)
        return await self._create(turn, draft)

    async def create_confirmed(self, turn: Turn, intent: Intent) -> Outcome:
        """Создаёт запись, несмотря на дубль или пересечение: пользователь согласился."""
        return await self._create(turn, creation_draft(intent, turn.now))

    async def _meeting_conflicts(self, turn: Turn, draft: EventDraft) -> list[EventCard]:
        if draft.type is not EventType.MEETING or draft.starts_at is None or draft.ends_at is None:
            return []
        slot = MeetingSlot(turn.profile_id, draft.starts_at, draft.ends_at)
        return await self._conflicts.find(slot)

    async def _create(self, turn: Turn, draft: EventDraft) -> Outcome:
        card = await self._editor.create(turn.profile_id, draft)
        ticket = await self._undo.record(turn.profile_id, RemoveCreated(card.id), turn.now)
        reply = Reply(
            ReplyKind.CONFIRMATION,
            phrases.created(card, turn.today),
            events=(card,),
            undo=ticket,
        )
        return Outcome(reply, focus=(card.id,))


def _confirm_duplicate(intent: Intent, existing: EventCard, turn: Turn) -> Outcome:
    question = PendingQuestion(
        PendingExpectation.CONFIRM, phrases.duplicate_question(existing, turn.today)
    )
    reply = Reply(
        ReplyKind.CONFIRM_REQUEST, question.question, events=(existing,), pending=question
    )
    return Outcome(reply, pending=PendingStep(question, intent), focus=(existing.id,))


def _confirm_despite_conflicts(intent: Intent, conflicts: list[EventCard]) -> Outcome:
    question = PendingQuestion(
        PendingExpectation.CONFIRM, phrases.conflict_question(conflicts, phrases.ADD_ANYWAY)
    )
    reply = Reply(
        ReplyKind.CONFIRM_REQUEST, question.question, conflicts=conflicts, pending=question
    )
    return Outcome(reply, pending=PendingStep(question, intent))
