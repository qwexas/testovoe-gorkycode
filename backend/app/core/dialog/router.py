"""Что делать с разобранной репликой: новая команда или ответ на вопрос ассистента.

Ответ, выбор, «да» и «нет» относятся к отложенному шагу (`Turn.pending`). Любая
другая команда отложенный шаг сбрасывает и выполняется как новая.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType

from app.core.dialog import phrases
from app.core.dialog.changes import ChangeFlow
from app.core.dialog.conflicts import ConflictFinder
from app.core.dialog.creation import CreationFlow
from app.core.dialog.lookup import ListingFlow, SearchFlow
from app.core.dialog.models import Outcome, PendingQuestion, PendingStep, Reply, Turn
from app.core.dialog.relevance import by_date, timeliness
from app.core.dialog.rules import merge_answer
from app.core.dialog.targets import TargetFinder, TargetLookup
from app.core.dialog.undo import UndoLog
from app.core.enums import PendingExpectation, ReplyKind
from app.core.errors import EventNotFoundError
from app.core.events import EventCard, EventEditor, EventService
from app.core.search import SearchService
from app.nlu.interfaces import Action, Intent
from app.storage.database import UnitOfWork

CHOICE_LIMIT = 5
"""Сколько вариантов показывать, когда подходит несколько записей."""
MIN_MATCH_WORD_LENGTH = 3

Command = Callable[[Turn, Intent], Awaitable[Outcome]]
FollowUp = Callable[[Turn, Intent, PendingStep], Awaitable[Outcome]]

_WITHOUT_QUESTION: Mapping[Action, str] = MappingProxyType(
    {Action.DENY: phrases.NOTHING_TO_DECLINE}
)
"""Ответ на «нет» и т. п., когда ассистент ни о чём не спрашивал; иначе — `NOT_UNDERSTOOD`."""

_REPEATED_KINDS: Mapping[PendingExpectation, ReplyKind] = MappingProxyType(
    {
        PendingExpectation.CHOICE: ReplyKind.CHOICE,
        PendingExpectation.CONFIRM: ReplyKind.CONFIRM_REQUEST,
    }
)


class DialogRouter:
    """Выбирает сценарий по `Intent` и состоянию диалога."""

    def __init__(self, storage: UnitOfWork, search: SearchService, undo: UndoLog) -> None:
        self._editor = EventEditor(storage, search)
        reader = EventService(storage, search)
        conflicts = ConflictFinder(storage)
        self._undo = undo
        self._creation = CreationFlow(self._editor, conflicts, undo)
        self._changes = ChangeFlow(self._editor, conflicts, undo)
        self._targets = TargetFinder(reader)
        self._commands: Mapping[Action, Command] = MappingProxyType(
            {
                Action.CREATE: self._creation.start,
                Action.LIST: ListingFlow(reader).run,
                Action.SEARCH: SearchFlow(reader).run,
                Action.RESCHEDULE: self._change,
                Action.RENAME: self._change,
                Action.COMPLETE: self._change,
                Action.DELETE: self._change,
                Action.UNDO: self._undo_latest,
                Action.SMALLTALK: _smalltalk,
                Action.UNKNOWN: self._unknown,
            }
        )
        self._follow_ups: Mapping[Action, FollowUp] = MappingProxyType(
            {
                Action.ANSWER: self._answer,
                Action.CHOOSE: self._choose,
                Action.CONFIRM: self._confirm,
                Action.DENY: _deny,
            }
        )

    async def route(self, turn: Turn, intent: Intent) -> Outcome:
        """Ответ ассистента на реплику.

        Выполняется одна команда — первая. Остальные команды реплики (`intent.unhandled`)
        не теряются молча: ответ называет их и просит повторить отдельно.
        """
        outcome = await self._route(turn, intent)
        if intent.unhandled is None:
            return outcome
        text = f"{outcome.reply.text} {phrases.unhandled_commands(intent.unhandled)}"
        return replace(outcome, reply=replace(outcome.reply, text=text))

    async def _route(self, turn: Turn, intent: Intent) -> Outcome:
        if turn.pending is not None and _moves_pending_record(intent, turn.pending):
            return await self._answer(turn, replace(intent, action=Action.ANSWER), turn.pending)
        follow_up = self._follow_ups.get(intent.action)
        if follow_up is None:
            return await self._commands[intent.action](turn, intent)
        if turn.pending is None:
            return Outcome.say(_WITHOUT_QUESTION.get(intent.action, phrases.NOT_UNDERSTOOD))
        return await follow_up(turn, intent, turn.pending)

    async def _change(self, turn: Turn, intent: Intent) -> Outcome:
        lookup = await self._targets.find(turn, intent)
        candidates = lookup.candidates
        if not candidates:
            return Outcome.say(_nothing_to_change(lookup))
        if len(candidates) == 1:
            return await self._changes.apply(turn, intent, candidates[0])
        return _offer_choice(intent, lookup, turn.now)

    async def _unknown(self, turn: Turn, intent: Intent) -> Outcome:
        """Не про задачи и встречи: без вопроса — подсказка, при вопросе — повторить его."""
        if turn.pending is None:
            return Outcome.say(phrases.OFF_TOPIC)
        return await self._repeat(turn, turn.pending, phrases.REPLY_NOT_UNDERSTOOD)

    async def _undo_latest(self, turn: Turn, intent: Intent) -> Outcome:
        reply = await self._undo.undo_latest(turn.profile_id, turn.now)
        return Outcome(reply, focus=tuple(card.id for card in reply.events))

    async def _answer(self, turn: Turn, answer: Intent, pending: PendingStep) -> Outcome:
        expects = pending.question.expects
        if expects is PendingExpectation.CHOICE:
            return await self._choose(turn, answer, pending)
        merged = merge_answer(pending.intent, answer, expects)
        if merged.action is Action.CREATE:
            return await self._creation.start(turn, merged)
        target = await self._pending_target(turn, pending)
        if target is None:
            return Outcome.say(phrases.EVENT_GONE)
        return await self._changes.apply(turn, merged, target)

    async def _choose(self, turn: Turn, choice: Intent, pending: PendingStep) -> Outcome:
        if pending.question.expects is not PendingExpectation.CHOICE:
            return await self._repeat(turn, pending)
        target_id = await self._chosen_id(turn, choice, pending)
        if target_id is None:
            lead = phrases.choice_out_of_range(len(pending.option_ids))
            return await self._repeat(turn, pending, lead)
        target = await self._event(turn, target_id)
        if target is None:
            return Outcome.say(phrases.EVENT_GONE)
        return await self._changes.apply(turn, pending.intent, target)

    async def _chosen_id(self, turn: Turn, choice: Intent, pending: PendingStep) -> int | None:
        """Выбранный вариант: по номеру («вторую») или по словам названия («с Ольгой»)."""
        option_ids = pending.option_ids
        if choice.choice_index is not None:
            in_range = 1 <= choice.choice_index <= len(option_ids)
            return option_ids[choice.choice_index - 1] if in_range else None
        matched = _match_by_title(await self._options(turn, pending), choice)
        return None if matched is None else matched.id

    async def _confirm(self, turn: Turn, intent: Intent, pending: PendingStep) -> Outcome:
        if pending.question.expects is not PendingExpectation.CONFIRM:
            return await self._repeat(turn, pending)
        if pending.intent.action is Action.CREATE:
            return await self._creation.create_confirmed(turn, pending.intent)
        target = await self._pending_target(turn, pending)
        if target is None:
            return Outcome.say(phrases.EVENT_GONE)
        return await self._changes.confirm(turn, pending.intent, target)

    async def _repeat(self, turn: Turn, pending: PendingStep, lead: str | None = None) -> Outcome:
        """Повторяет вопрос, если ответ к нему не подошёл; отложенный шаг сохраняется."""
        question = pending.question
        kind = _REPEATED_KINDS.get(question.expects, ReplyKind.CLARIFICATION)
        target = await self._pending_target(turn, pending)
        reply = Reply(
            kind,
            question.question if lead is None else f"{lead} {question.question}",
            events=() if target is None else (target,),
            choices=await self._options(turn, pending),
            pending=question,
        )
        return Outcome(reply, pending=pending)

    async def _pending_target(self, turn: Turn, pending: PendingStep) -> EventCard | None:
        return None if pending.target_id is None else await self._event(turn, pending.target_id)

    async def _options(self, turn: Turn, pending: PendingStep) -> list[EventCard]:
        options = [await self._event(turn, event_id) for event_id in pending.option_ids]
        return [card for card in options if card is not None]

    async def _event(self, turn: Turn, event_id: int) -> EventCard | None:
        try:
            return await self._editor.get(turn.profile_id, event_id)
        except EventNotFoundError:
            return None


def _moves_pending_record(intent: Intent, pending: PendingStep) -> bool:
    """«А перенеси её на послезавтра», пока запись ещё создаётся (уточнение или конфликт).

    «Её» здесь — создаваемая запись: новое время — это ответ на вопрос, а не перенос другой
    записи (иначе при конфликте переехала бы мешающая встреча). Запись, описанная днём
    и временем («перенеси завтрашнюю встречу в 10…»), — уже существующая, не создаваемая.
    """
    target = intent.target
    return (
        pending.intent.action is Action.CREATE
        and intent.action is Action.RESCHEDULE
        and intent.when is not None
        and not intent.when.is_empty
        and (target is None or target.last or not (target.query or target.when))
    )


def _nothing_to_change(lookup: TargetLookup) -> str:
    """Ссылка «её» без контекста — непонятно о чём; поиск без результата — не нашёл."""
    if lookup.query is not None:
        return phrases.target_not_found(lookup.query)
    return phrases.TARGET_UNCLEAR if lookup.moment is None else phrases.NOTHING_AT_MOMENT


def _offer_choice(intent: Intent, lookup: TargetLookup, now: datetime) -> Outcome:
    """Несколько подходящих записей — пронумерованный список (Q33).

    Если подходящих больше `CHOICE_LIMIT`, показываются самые актуальные: ближайшие будущие,
    затем самые свежие прошедшие. Варианты нумеруются по дате, записи без даты — в конце.
    На «её» после ответа-списка ассистент ничего не искал — звучит только вопрос «Какое…?».
    """
    candidates = lookup.candidates
    most_timely = sorted(candidates, key=lambda card: timeliness(card, now))[:CHOICE_LIMIT]
    options = tuple(by_date(most_timely))
    noun = phrases.ENTRY
    types = {card.type for card in options}
    if len(types) == 1:
        noun = phrases.noun_of(next(iter(types)))
    question = PendingQuestion(
        PendingExpectation.CHOICE, phrases.choice_question(intent.action, noun)
    )
    text = (
        question.question
        if lookup.query is None and lookup.moment is None
        else phrases.choice_text(intent.action, noun, shown=len(options), total=len(candidates))
    )
    ids = tuple(card.id for card in options)
    reply = Reply(ReplyKind.CHOICE, text, choices=options, pending=question)
    step = PendingStep(question, intent, option_ids=ids)
    return Outcome(reply, pending=step, focus=ids, peer_focus=True)


def _match_by_title(options: list[EventCard], choice: Intent) -> EventCard | None:
    """Вариант, в названии которого больше всего слов ответа; `None` — неоднозначно."""
    spoken = choice.title or choice.query or choice.text
    words = {word for word in spoken.casefold().split() if len(word) >= MIN_MATCH_WORD_LENGTH}
    scores = [sum(word in card.title.casefold() for word in words) for card in options]
    best = max(scores, default=0)
    if best == 0 or scores.count(best) > 1:
        return None
    return options[scores.index(best)]


async def _smalltalk(turn: Turn, intent: Intent) -> Outcome:
    return Outcome.say(phrases.SMALLTALK)


async def _deny(turn: Turn, intent: Intent, pending: PendingStep) -> Outcome:
    return Outcome.say(phrases.declined(pending.question.expects, pending.intent.action))
