"""Записи для ленты дня и кнопок интерфейса (голосом то же делается через `/api/chat`)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from pydantic import AwareDatetime

from app.api.dependencies import CURRENT_PROFILE_RESPONSES, CurrentProfile, Events
from app.api.errors import error_responses
from app.api.schemas.events import Event, EventCreate, EventsResponse, EventUpdate
from app.core.enums import EventStatus, EventType
from app.core.errors import ErrorCode
from app.core.events import KEEP, EventCard, EventChanges, EventDraft
from app.core.queries import EventFilter

EVENTS_PAGE_DEFAULT = 50
EVENTS_PAGE_MAX = 200
SEARCH_QUERY_MAX_LENGTH = 200

router = APIRouter(tags=["events"], responses=CURRENT_PROFILE_RESPONSES)

EventId = Annotated[int, Path(alias="id", ge=1)]


@router.get(
    "/events",
    name="list_events",
    summary="Список записей",
    description=(
        "Период — полуинтервал `[from, to)` по началу записи. Если задан `q`, ищет по смыслу "
        "среди записей, подходящих под остальные фильтры, и сортирует по релевантности; "
        "иначе — по времени начала, записи без даты в конце."
    ),
    response_model=EventsResponse,
    responses=error_responses(ErrorCode.VALIDATION_ERROR),
)
async def list_events(
    profile: CurrentProfile,
    events: Events,
    period_start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    period_end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    event_type: Annotated[EventType | None, Query(alias="type")] = None,
    event_status: Annotated[EventStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=SEARCH_QUERY_MAX_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=EVENTS_PAGE_MAX)] = EVENTS_PAGE_DEFAULT,
) -> EventsResponse:
    criteria = EventFilter(
        profile_id=profile.id,
        period_start=period_start,
        period_end=period_end,
        event_types=None if event_type is None else frozenset({event_type}),
        status=event_status,
    )
    query = (q or "").strip()
    if query:
        found = await events.search_events(criteria, query, limit)
    else:
        found = await events.list_events(criteria, limit)
    return EventsResponse(events=[_to_event_schema(card) for card in found])


@router.post(
    "/events",
    name="create_event",
    summary="Создать запись",
    description=(
        "У встречи и напоминания обязательны дата и время. Конец (`ends_at`) — только у "
        "встречи, по умолчанию начало + 60 минут. При `has_time: false` время начала "
        "становится 00:00 по Москве."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=Event,
    responses=error_responses(ErrorCode.VALIDATION_ERROR),
)
async def create_event(body: EventCreate, profile: CurrentProfile, events: Events) -> Event:
    draft = EventDraft(
        type=body.type,
        title=body.title,
        starts_at=body.starts_at,
        has_time=body.has_time,
        ends_at=body.ends_at,
    )
    return _to_event_schema(await events.create(profile.id, draft))


@router.patch(
    "/events/{id}",
    name="update_event",
    summary="Изменить запись",
    description=(
        'В том числе отметить выполненной: `status: "done"`. `null` у `starts_at` и '
        "`ends_at` стирает значение, у остальных полей — оставляет как есть. Перенос "
        "встречи без `ends_at` сохраняет её длительность."
    ),
    response_model=Event,
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND),
)
async def update_event(
    event_id: EventId, body: EventUpdate, profile: CurrentProfile, events: Events
) -> Event:
    sent = body.model_fields_set
    changes = EventChanges(
        title=body.title,
        starts_at=body.starts_at if "starts_at" in sent else KEEP,
        has_time=body.has_time,
        ends_at=body.ends_at if "ends_at" in sent else KEEP,
        status=body.status,
    )
    return _to_event_schema(await events.update(profile.id, event_id, changes))


@router.delete(
    "/events/{id}",
    name="delete_event",
    summary="Удалить запись",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND),
)
async def delete_event(event_id: EventId, profile: CurrentProfile, events: Events) -> None:
    await events.delete(profile.id, event_id)


def _to_event_schema(card: EventCard) -> Event:
    return Event.model_validate(card, from_attributes=True)
