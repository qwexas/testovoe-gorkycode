"""Схемы диалога с ассистентом."""

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.api.schemas.base import RequestModel, ResponseModel
from app.api.schemas.events import Event
from app.core.enums import MessageRole, PendingExpectation, ReplyKind

UTTERANCE_MAX_LENGTH = 1000
VOICE_NAME_MAX_LENGTH = 32

Utterance = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=UTTERANCE_MAX_LENGTH)
]


class Period(ResponseModel):
    """Период, за который показан список."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    from_: datetime = Field(alias="from")
    to: datetime
    label: str = Field(examples=["сегодня", "на этой неделе"])


class Choice(ResponseModel):
    """Пронумерованный вариант, когда подходит несколько записей."""

    index: int = Field(ge=1, description="Номер варианта, с 1")
    event: Event


class Pending(ResponseModel):
    """Чего ассистент ждёт от пользователя."""

    expects: PendingExpectation
    question: str


class Undo(ResponseModel):
    """Действие можно отменить до `expires_at`.

    Сервер принимает отмену 30 секунд; кнопку «Отменить» интерфейс показывает 10 секунд,
    оставшееся время — запас на сеть и на голосовую команду «отмени».
    """

    action_id: str = Field(description="Для `POST /api/actions/{action_id}/undo`")
    expires_at: datetime = Field(description="Срок отмены на сервере: момент действия + 30 с")


class AssistantReply(ResponseModel):
    """Ответ ассистента на реплику."""

    message_id: int = Field(description="id реплики ассистента в истории")
    kind: ReplyKind
    text: str = Field(description="Текст ответа; его же озвучиваем")
    recognized_text: str | None = Field(
        description="Что распознано из голоса (только для `/api/voice`)"
    )
    events: list[Event] = Field(description="Созданные / изменённые / найденные записи")
    period: Period | None
    choices: list[Choice]
    conflicts: list[Event] = Field(description="Встречи, с которыми пересекается новая")
    pending: Pending | None
    undo: Undo | None


class ChatMessage(ResponseModel):
    """Реплика в истории диалога."""

    id: int
    role: MessageRole
    text: str
    created_at: datetime
    reply: AssistantReply | None = Field(description="Полный ответ — для реплик ассистента")


class DialogResponse(ResponseModel):
    """История диалога, новые реплики в конце."""

    messages: list[ChatMessage]


class ChatRequest(RequestModel):
    """Текстовая реплика пользователя."""

    text: Utterance


class TtsRequest(RequestModel):
    """Текст для озвучки."""

    text: Utterance
    voice: str | None = Field(default=None, max_length=VOICE_NAME_MAX_LENGTH)
