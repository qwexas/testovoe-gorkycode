"""Экспорт в календарь: файл `.ics` и подписка `webcal://` по секретному токену (Q27).

Что попадает в календарь и какие у записей предупреждения — `app.core.calendar`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Response

from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CalendarFeed, ClientIp, CurrentProfile
from app.api.errors import error_responses
from app.core.errors import ErrorCode
from app.storage.models import TOKEN_LENGTH

CALENDAR_MEDIA_TYPE = "text/calendar; charset=utf-8"
DOWNLOAD_HEADERS = {
    "Content-Disposition": 'attachment; filename="gorky.ics"',
    "Cache-Control": "no-store",
}
SUBSCRIPTION_HEADERS = {"Cache-Control": "no-cache"}
"""Подписку клиент перечитывает сам; промежуточным кэшам — всегда сверяться с сервером."""

router = APIRouter(tags=["calendar"])

CalendarToken = Annotated[str, Path(min_length=1, max_length=TOKEN_LENGTH)]


def _calendar_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    return {
        200: {
            "description": "Календарь iCalendar (RFC 5545)",
            "content": {"text/calendar": {"schema": {"type": "string"}}},
        },
        **error_responses(*codes),
    }


@router.get(
    "/calendar.ics",
    name="download_calendar",
    summary="Скачать .ics",
    description=(
        "Открытые записи профиля с датой, начиная с сегодняшнего дня, файлом `gorky.ics`. "
        "Встречи — с предупреждением за 15 минут, напоминания и задачи со временем — "
        "в момент начала, задачи на день — в 09:00."
    ),
    response_class=Response,
    responses=_calendar_responses() | CURRENT_PROFILE_RESPONSES,
)
async def download_calendar(profile: CurrentProfile, calendar: CalendarFeed) -> Response:
    content = await calendar.for_profile(profile.id)
    return Response(content=content, media_type=CALENDAR_MEDIA_TYPE, headers=DOWNLOAD_HEADERS)


@router.get(
    "/calendar/{token}.ics",
    name="subscribe_calendar",
    summary="Подписка на календарь",
    description=(
        "То же, что `/api/calendar.ics`, по секретному токену из `calendar_subscription_url` "
        "— без cookie, профиль не создаётся. Неизвестный токен — 404. Лимит — 60 запросов "
        "в минуту с одного IP."
    ),
    response_class=Response,
    responses=_calendar_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.RATE_LIMITED
    ),
)
async def subscribe_calendar(
    token: CalendarToken, client_ip: ClientIp, calendar: CalendarFeed
) -> Response:
    content = await calendar.for_subscription(token, requester=client_ip)
    return Response(content=content, media_type=CALENDAR_MEDIA_TYPE, headers=SUBSCRIPTION_HEADERS)
