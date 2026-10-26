"""Диалог с ассистентом: текст, история, отмена действия; голос и озвучка — позже.

`/api/voice` и `/api/tts` объявлены по контракту и пока отвечают 501 (контрольная точка 4).
"""

from typing import Annotated

from fastapi import APIRouter, File, Path, Query, Response, UploadFile

from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CurrentProfile, Dialog
from app.api.errors import error_responses
from app.api.schemas.dialog import (
    AssistantReply,
    ChatMessage,
    ChatRequest,
    DialogResponse,
    TtsRequest,
)
from app.core.dialog.models import AssistantAnswer, DialogEntry
from app.core.dialog.payloads import answer_payload
from app.core.enums import MessageSource
from app.core.errors import ErrorCode, FeatureNotImplementedError
from app.storage.models import TOKEN_LENGTH

DIALOG_PAGE_DEFAULT = 50
DIALOG_PAGE_MAX = 200

router = APIRouter(tags=["dialog"], responses=CURRENT_PROFILE_RESPONSES)

ActionId = Annotated[str, Path(min_length=1, max_length=TOKEN_LENGTH)]


@router.post(
    "/chat",
    name="send_chat_message",
    summary="Текстовая реплика",
    description=(
        "Лимит — 20 запросов в минуту на профиль (вместе с `/api/voice`). Реплика "
        "пользователя сохраняется в историю до разбора: при 503 `llm_unavailable` она "
        "остаётся в истории, а ответа ассистента нет."
    ),
    response_model=AssistantReply,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.RATE_LIMITED, ErrorCode.LLM_UNAVAILABLE
    ),
)
async def send_chat_message(
    body: ChatRequest, profile: CurrentProfile, dialog: Dialog
) -> AssistantReply:
    answer = await dialog.handle(profile.id, body.text, MessageSource.TEXT)
    return _to_reply_schema(answer)


@router.post(
    "/voice",
    name="send_voice_message",
    summary="Голосовая реплика",
    description=(
        "Аудио webm/opus, ogg, mp4/aac или wav, не больше 10 МБ и 60 секунд. "
        "Аудио не сохраняется. В ответе заполнен `recognized_text`."
    ),
    response_model=AssistantReply,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.SPEECH_NOT_RECOGNIZED,
        ErrorCode.AUDIO_UNSUPPORTED,
        ErrorCode.AUDIO_TOO_LARGE,
        ErrorCode.RATE_LIMITED,
        ErrorCode.STT_UNAVAILABLE,
        ErrorCode.LLM_UNAVAILABLE,
        ErrorCode.NOT_IMPLEMENTED,
    ),
)
async def send_voice_message(
    audio: Annotated[UploadFile, File(description="Запись голоса")],
    profile: CurrentProfile,
) -> AssistantReply:
    raise FeatureNotImplementedError()


@router.get(
    "/dialog",
    name="get_dialog",
    summary="История диалога",
    description="Новые реплики в конце. `before_id` — для подгрузки более старых.",
    response_model=DialogResponse,
    responses=error_responses(ErrorCode.VALIDATION_ERROR),
)
async def get_dialog(
    profile: CurrentProfile,
    dialog: Dialog,
    limit: Annotated[int, Query(ge=1, le=DIALOG_PAGE_MAX)] = DIALOG_PAGE_DEFAULT,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> DialogResponse:
    entries = await dialog.history(profile.id, limit, before_id)
    return DialogResponse(messages=[_to_message_schema(entry) for entry in entries])


@router.post(
    "/tts",
    name="synthesize_speech",
    summary="Озвучка ответа",
    response_class=Response,
    responses={
        200: {
            "description": "Аудио OGG/Opus",
            "content": {"audio/ogg": {"schema": {"type": "string", "format": "binary"}}},
        },
        **error_responses(
            ErrorCode.VALIDATION_ERROR, ErrorCode.TTS_UNAVAILABLE, ErrorCode.NOT_IMPLEMENTED
        ),
    },
)
async def synthesize_speech(body: TtsRequest, profile: CurrentProfile) -> Response:
    raise FeatureNotImplementedError()


@router.post(
    "/actions/{action_id}/undo",
    name="undo_action",
    summary="Отменить действие",
    description=(
        "Отменяет создание, перенос, переименование, отметку о выполнении или удаление. "
        "Сервер принимает отмену 30 секунд после действия (кнопку интерфейс показывает "
        "10 секунд — запас на сеть). Позже, повторно или для чужого действия — 404."
    ),
    response_model=AssistantReply,
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND),
)
async def undo_action(
    action_id: ActionId, profile: CurrentProfile, dialog: Dialog
) -> AssistantReply:
    return _to_reply_schema(await dialog.undo_action(profile.id, action_id))


def _to_reply_schema(answer: AssistantAnswer) -> AssistantReply:
    return AssistantReply.model_validate(answer_payload(answer))


def _to_message_schema(entry: DialogEntry) -> ChatMessage:
    return ChatMessage(
        id=entry.id,
        role=entry.role,
        text=entry.text,
        created_at=entry.created_at,
        reply=None if entry.reply is None else AssistantReply.model_validate(entry.reply),
    )
