"""Диалог с ассистентом: текст, голос, история, озвучка ответа, отмена действия."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response

from app.api.audio_upload import VOICE_REQUEST_BODY, read_audio_upload
from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CurrentProfile, Dialog, Synthesis
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
from app.core.errors import ErrorCode
from app.storage.models import TOKEN_LENGTH

DIALOG_PAGE_DEFAULT = 50
DIALOG_PAGE_MAX = 200
NO_STORE = {"Cache-Control": "no-store"}

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
        "Форма с полем `audio`: webm/opus, ogg, mp4/aac, wav или mpeg, не больше 10 МБ "
        "и 60 секунд. Распознанный текст обрабатывается как реплика `/api/chat` "
        "(общий лимит 20 в минуту) и приходит в `recognized_text`. Тишина или шум — "
        "422 `speech_not_recognized`. Аудио не сохраняется и не пишется в лог: "
        "в истории остаётся только распознанный текст."
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
    ),
    openapi_extra={"requestBody": VOICE_REQUEST_BODY},
)
async def send_voice_message(
    request: Request, profile: CurrentProfile, dialog: Dialog
) -> AssistantReply:
    audio = await read_audio_upload(request)
    return _to_reply_schema(await dialog.handle_voice(profile.id, audio))


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
    description=(
        "Аудио OGG/Opus, не кэшируется. `voice` — один из голосов Silero, без него — "
        "голос по умолчанию; неизвестный голос — 422. Лимит — 40 запросов в минуту "
        "на профиль."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Аудио OGG/Opus",
            "content": {"audio/ogg": {"schema": {"type": "string", "format": "binary"}}},
        },
        **error_responses(
            ErrorCode.VALIDATION_ERROR, ErrorCode.RATE_LIMITED, ErrorCode.TTS_UNAVAILABLE
        ),
    },
)
async def synthesize_speech(
    body: TtsRequest, profile: CurrentProfile, synthesis: Synthesis
) -> Response:
    audio = await synthesis.synthesize(profile.id, body.text, body.voice)
    return Response(content=audio.data, media_type=audio.content_type, headers=NO_STORE)


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
