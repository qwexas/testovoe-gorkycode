"""Записи для ленты дня и кнопок интерфейса (голосом то же делается через `/api/chat`).

На контрольной точке 1 маршруты объявлены по контракту и отвечают 501.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from pydantic import AwareDatetime

from app.api.dependencies import CurrentProfile
from app.api.errors import error_responses
from app.api.schemas.events import Event, EventCreate, EventsResponse, EventUpdate
from app.core.enums import EventStatus, EventType
from app.core.errors import ErrorCode, FeatureNotImplementedError

EVENTS_PAGE_DEFAULT = 50
EVENTS_PAGE_MAX = 200
SEARCH_QUERY_MAX_LENGTH = 200

router = APIRouter(tags=["events"])

EventId = Annotated[int, Path(alias="id", ge=1)]


@router.get(
    "/events",
    name="list_events",
    summary="Список записей",
    description="Если задан `q`, ищет по смыслу и сортирует по релевантности.",
    response_model=EventsResponse,
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_IMPLEMENTED),
)
async def list_events(
    profile: CurrentProfile,
    period_start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    period_end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    event_type: Annotated[EventType | None, Query(alias="type")] = None,
    event_status: Annotated[EventStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=SEARCH_QUERY_MAX_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=EVENTS_PAGE_MAX)] = EVENTS_PAGE_DEFAULT,
) -> EventsResponse:
    raise FeatureNotImplementedError()


@router.post(
    "/events",
    name="create_event",
    summary="Создать запись",
    status_code=status.HTTP_201_CREATED,
    response_model=Event,
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_IMPLEMENTED),
)
async def create_event(body: EventCreate, profile: CurrentProfile) -> Event:
    raise FeatureNotImplementedError()


@router.patch(
    "/events/{id}",
    name="update_event",
    summary="Изменить запись",
    description='В том числе отметить выполненной: `status: "done"`.',
    response_model=Event,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.NOT_IMPLEMENTED
    ),
)
async def update_event(event_id: EventId, body: EventUpdate, profile: CurrentProfile) -> Event:
    raise FeatureNotImplementedError()


@router.delete(
    "/events/{id}",
    name="delete_event",
    summary="Удалить запись",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.NOT_IMPLEMENTED
    ),
)
async def delete_event(event_id: EventId, profile: CurrentProfile) -> None:
    raise FeatureNotImplementedError()
