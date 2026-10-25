"""Диалог с ассистентом: текст, голос, история, озвучка, отмена действия.

На контрольной точке 1 маршруты объявлены по контракту и отвечают 501.
"""

from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CurrentProfile
from app.api.errors import error_responses
from app.api.schemas.dialog import AssistantReply, ChatRequest, DialogResponse, TtsRequest
from app.core.errors import ErrorCode, FeatureNotImplementedError

DIALOG_PAGE_DEFAULT = 50
DIALOG_PAGE_MAX = 200

router = APIRouter(tags=["dialog"], responses=CURRENT_PROFILE_RESPONSES)


@router.post(
    "/chat",
    name="send_chat_message",
    summary="Текстовая реплика",
    description="Лимит — 20 запросов в минуту на профиль (вместе с `/api/voice`).",
    response_model=AssistantReply,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.RATE_LIMITED,
        ErrorCode.LLM_UNAVAILABLE,
        ErrorCode.NOT_IMPLEMENTED,
    ),
)
async def send_chat_message(body: ChatRequest, profile: CurrentProfile) -> AssistantReply:
    raise FeatureNotImplementedError()


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
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_IMPLEMENTED),
)
async def get_dialog(
    profile: CurrentProfile,
    limit: Annotated[int, Query(ge=1, le=DIALOG_PAGE_MAX)] = DIALOG_PAGE_DEFAULT,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> DialogResponse:
    raise FeatureNotImplementedError()


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
    description="Работает 10 секунд после действия, потом — 404.",
    response_model=AssistantReply,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.NOT_IMPLEMENTED
    ),
)
async def undo_action(action_id: str, profile: CurrentProfile) -> AssistantReply:
    raise FeatureNotImplementedError()
