"""Экспорт в календарь: файл `.ics` и подписка `webcal://` по секретному токену.

На контрольной точке 1 маршруты объявлены по контракту и отвечают 501.
"""

from typing import Any

from fastapi import APIRouter, Response

from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CurrentProfile
from app.api.errors import error_responses
from app.core.errors import ErrorCode, FeatureNotImplementedError

router = APIRouter(tags=["calendar"])


def _calendar_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    return {
        200: {
            "description": "Календарь iCalendar",
            "content": {"text/calendar": {"schema": {"type": "string"}}},
        },
        **error_responses(*codes),
    }


@router.get(
    "/calendar.ics",
    name="download_calendar",
    summary="Скачать .ics",
    description="Все предстоящие записи профиля, файлом (attachment).",
    response_class=Response,
    responses=_calendar_responses(ErrorCode.NOT_IMPLEMENTED) | CURRENT_PROFILE_RESPONSES,
)
async def download_calendar(profile: CurrentProfile) -> Response:
    raise FeatureNotImplementedError()


@router.get(
    "/calendar/{token}.ics",
    name="subscribe_calendar",
    summary="Подписка на календарь",
    description="По секретному токену, без cookie. Напоминания — с `VALARM`.",
    response_class=Response,
    responses=_calendar_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.NOT_IMPLEMENTED
    ),
)
async def subscribe_calendar(token: str) -> Response:
    raise FeatureNotImplementedError()
