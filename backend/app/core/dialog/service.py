"""Диалог с ассистентом: реплика → разбор → действие → ответ, история и отмена.

Сервис не знает про HTTP. Разбор реплики делает `IntentParser` (ИИ-часть), решения
принимает `DialogRouter`, тексты ответов — шаблоны `phrases` (Q24).
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.core.admission import LOCAL_CLIENT, DialogAdmission
from app.core.dialog.models import AssistantAnswer, DialogEntry, Reply, Turn
from app.core.dialog.payloads import answer_payload
from app.core.dialog.router import DialogRouter
from app.core.dialog.state import DialogState
from app.core.dialog.undo import UndoLog
from app.core.enums import MessageRole, MessageSource
from app.core.errors import TooManyMessagesError, TurnTimeoutError
from app.core.events import EventCard, EventEditor
from app.core.rate_limit import Throttle
from app.core.schedule import MOSCOW, moscow_now
from app.core.search import SearchService
from app.core.speech import recognize_speech
from app.nlu.interfaces import ContextEvent, DialogContext, IntentParser
from app.storage.database import UnitOfWork
from app.storage.models import ChatMessageRecord
from app.voice.interfaces import AudioClip, SpeechToText

MESSAGES_PER_WINDOW = 20
MESSAGE_WINDOW_SECONDS = 60
TEXT_TURN_SECONDS = 50.0
"""Сколько может длиться текстовый ход — меньше таймаута nginx (60 с)."""
VOICE_TURN_SECONDS = 85.0
"""Сколько может длиться голосовой ход — меньше таймаута nginx для `/api/voice` (95 с)."""
ACTION_RESERVE_SECONDS = 3.0
"""Запас на выполнение действия и запись в БД после разбора."""

Clock = Callable[[], datetime]


class MessageThrottle(Throttle):
    """Не больше `MESSAGES_PER_WINDOW` реплик в минуту на профиль (текст и голос вместе)."""

    max_hits = MESSAGES_PER_WINDOW
    window_seconds = MESSAGE_WINDOW_SECONDS
    rejection = TooManyMessagesError


@dataclass(frozen=True, slots=True)
class DialogDependencies:
    """Долгоживущие зависимости диалога; собираются в `app.factory`."""

    parser: IntentParser
    search: SearchService
    throttle: MessageThrottle
    speech: SpeechToText
    clock: Clock = field(default=moscow_now)
    admission: DialogAdmission = field(default_factory=DialogAdmission)
    """Общая на процесс очередь реплик: в `app.factory` — одна на все запросы."""


class DialogService:
    """Сценарии диалога одного запроса; изменения фиксируются транзакцией `storage`."""

    def __init__(self, storage: UnitOfWork, dependencies: DialogDependencies) -> None:
        self._storage = storage
        self._parser = dependencies.parser
        self._speech = dependencies.speech
        self._throttle = dependencies.throttle
        self._clock = dependencies.clock
        self._admission = dependencies.admission
        self._undo = UndoLog(storage, EventEditor(storage, dependencies.search))
        self._router = DialogRouter(storage, dependencies.search, self._undo)

    async def handle(
        self, profile_id: UUID, text: str, source: MessageSource, client: str = LOCAL_CLIENT
    ) -> AssistantAnswer:
        """Отвечает на реплику пользователя и сохраняет обе реплики в историю.

        Реплика пользователя фиксируется до разбора: если LLM недоступна, она остаётся
        в истории, а ошибка `llm_unavailable` уходит вызывающему без ответа ассистента.
        Пока LLM думает, соединение с БД не занято; если ход не уложился в срок,
        ничего не выполняется (`TurnTimeoutError`).

        Raises:
            TooManyMessagesError: Профиль превысил лимит реплик в минуту.
            TooManyAttemptsError: Занята очередь профиля, IP или сервиса.
            TurnTimeoutError: Ход не уложился в срок.
            DomainError: Разбор реплики не удался (`llm_unavailable`).
        """
        self._throttle.admit(profile_id)
        deadline = _deadline(TEXT_TURN_SECONDS)
        async with self._turn(profile_id, client, deadline):
            return await self._answer(profile_id, text, source, deadline)

    async def handle_voice(
        self, profile_id: UUID, audio: AudioClip, client: str = LOCAL_CLIENT
    ) -> AssistantAnswer:
        """Голосовая реплика: распознаёт речь и отвечает, как на текст (`source=voice`).

        Лимит реплик общий с текстом и учитывается до распознавания: модель речи
        дорогая. В историю попадает только распознанный текст, аудио не сохраняется (Q35).

        Raises:
            TooManyMessagesError: Профиль превысил лимит реплик в минуту.
            TooManyAttemptsError: Занята очередь профиля, IP или сервиса.
            TurnTimeoutError: Ход не уложился в срок.
            SpeechNotRecognizedError: В записи нет речи.
            DomainError: Запись не подходит (`audio_unsupported`, `audio_too_large`),
                распознавание или LLM недоступны (`stt_unavailable`, `llm_unavailable`).
        """
        self._throttle.admit(profile_id)
        deadline = _deadline(VOICE_TURN_SECONDS)
        async with self._turn(profile_id, client, deadline):
            async with _until(deadline - ACTION_RESERVE_SECONDS):
                text = await recognize_speech(self._speech, audio)
            return await self._answer(profile_id, text, MessageSource.VOICE, deadline)

    async def undo_action(self, profile_id: UUID, action_id: str) -> AssistantAnswer:
        """Отменяет действие по кнопке «Отменить»; ответ попадает в историю.

        Raises:
            UndoUnavailableError: Действия нет, оно чужое, уже отменено или срок прошёл.
        """
        reply = await self._undo.undo(profile_id, action_id, self._clock())
        state = DialogState.from_record(await self._storage.dialog_states.get(profile_id))
        answer = await self._save_answer(profile_id, reply, recognized_text=None)
        await self._storage.dialog_states.save(state.after_undo(reply).to_record(profile_id))
        await self._storage.commit()
        return answer

    async def history(
        self, profile_id: UUID, limit: int, before_id: int | None = None
    ) -> list[DialogEntry]:
        """Последние `limit` реплик (раньше `before_id`, если задан), новые в конце."""
        messages = await self._storage.messages.list_before(profile_id, before_id, limit)
        return [
            DialogEntry(
                id=message.id,
                role=message.role,
                text=message.text,
                created_at=message.created_at.astimezone(MOSCOW),
                reply=message.reply,
            )
            for message in messages
        ]

    @asynccontextmanager
    async def _turn(self, profile_id: UUID, client: str, deadline: float) -> AsyncIterator[None]:
        """Очередь хода: ждать её дольше срока хода нельзя."""
        try:
            async with self._admission.enter(profile_id, client, deadline):
                yield
        except TimeoutError as error:
            raise TurnTimeoutError() from error

    async def _answer(
        self, profile_id: UUID, text: str, source: MessageSource, deadline: float
    ) -> AssistantAnswer:
        # Ходы профиля уже идут по очереди (`DialogAdmission`), поэтому состояние,
        # прочитанное до разбора, к записи не устареет. Соединение с БД на время
        # разбора возвращается в пул: commit сохраняет реплику и закрывает транзакцию.
        await self._add_user_message(profile_id, text)
        now = self._clock()
        state = DialogState.from_record(await self._storage.dialog_states.get(profile_id))
        focus = await self._focus_cards(profile_id, state.focus_ids)
        await self._storage.commit()

        async with _until(deadline - ACTION_RESERVE_SECONDS):
            intent = await self._parser.parse(text, _parser_context(now, state, focus))

        # Запасная блокировка строки профиля — на случай нескольких процессов.
        await self._storage.profiles.lock(profile_id)
        peer_ids = set(state.peer_ids)
        turn = Turn(
            profile_id=profile_id,
            now=now,
            pending=state.pending,
            focus=focus,
            peers=[card for card in focus if card.id in peer_ids],
        )
        outcome = await self._router.route(turn, intent)
        recognized_text = text if source is MessageSource.VOICE else None
        answer = await self._save_answer(profile_id, outcome.reply, recognized_text)
        next_state = state.after_turn(text, outcome)
        await self._storage.dialog_states.save(next_state.to_record(profile_id))
        await self._storage.commit()
        return answer

    async def _add_user_message(self, profile_id: UUID, text: str) -> None:
        message = ChatMessageRecord(profile_id=profile_id, role=MessageRole.USER, text=text)
        await self._storage.messages.add(message)

    async def _save_answer(
        self, profile_id: UUID, reply: Reply, recognized_text: str | None
    ) -> AssistantAnswer:
        """Сохраняет ответ ассистента; JSON ответа содержит `message_id` своей реплики."""
        message = ChatMessageRecord(
            profile_id=profile_id, role=MessageRole.ASSISTANT, text=reply.text
        )
        await self._storage.messages.add(message)
        answer = AssistantAnswer(message.id, reply, recognized_text)
        message.reply = answer_payload(answer)
        return answer

    async def _focus_cards(self, profile_id: UUID, focus_ids: Sequence[int]) -> list[EventCard]:
        records = await self._storage.events.get_many(profile_id, focus_ids)
        return [EventCard.from_record(record) for record in records]


def _deadline(seconds: float) -> float:
    return asyncio.get_running_loop().time() + seconds


@asynccontextmanager
async def _until(deadline: float) -> AsyncIterator[None]:
    """Блок должен закончиться до `deadline`; иначе ход прерывается до любых изменений."""
    try:
        async with asyncio.timeout_at(deadline):
            yield
    except TimeoutError as error:
        raise TurnTimeoutError() from error


def _parser_context(now: datetime, state: DialogState, focus: Sequence[EventCard]) -> DialogContext:
    pending = state.pending
    return DialogContext(
        now=now,
        pending=None if pending is None else pending.question.expects,
        pending_question=None if pending is None else pending.question.question,
        recent=state.recent,
        focus=tuple(
            ContextEvent(id=card.id, type=card.type, title=card.title, starts_at=card.starts_at)
            for card in focus
        ),
    )
