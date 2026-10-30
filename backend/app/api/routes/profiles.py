"""анонимный профиль: текущий, новый, вход по коду, удаление всех данных."""

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import (
    CURRENT_PROFILE_RESPONSES,
    AppSettings,
    ClientIp,
    CurrentProfile,
    OptionalSessionToken,
    Profiles,
)
from app.api.errors import error_responses
from app.api.profile_creation import require_profile_creation
from app.api.schemas.profiles import Profile, RestoreRequest
from app.api.session_cookie import issue_session_cookie, revoke_session_cookie
from app.config import Settings
from app.core.errors import ErrorCode
from app.core.profiles import ProfileCard
from app.core.schedule import PROFILE_TIMEZONE

router = APIRouter(tags=["profile"])


@router.get(
    "/me",
    name="get_me",
    summary="Текущий профиль",
    description="Читает существующий профиль. Без действующей сессии — 401; ничего не создаёт.",
    response_model=Profile,
    responses=CURRENT_PROFILE_RESPONSES,
)
async def get_me(profile: CurrentProfile, settings: AppSettings) -> Profile:
    return _to_profile_schema(profile, settings)


@router.post(
    "/profiles",
    name="create_profile",
    summary="Новый профиль",
    description=(
        "Создаёт профиль и переключает на него cookie этого устройства. "
        "Возвращает одноразовый recovery_code. Обязателен X-Gorky-Client: web. "
        "При наличии Origin он должен входить в PROFILE_CREATION_ORIGINS. "
        "Лимит — 20 новых профилей в час с одного IP."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=Profile,
    responses=error_responses(
        ErrorCode.RATE_LIMITED, ErrorCode.FORBIDDEN, ErrorCode.VALIDATION_ERROR
    ),
    dependencies=[Depends(require_profile_creation)],
)
async def create_profile(
    request: Request,
    session_token: OptionalSessionToken,
    client_ip: ClientIp,
    profiles: Profiles,
    settings: AppSettings,
) -> Profile:
    grant = await profiles.create_profile(replaced_session=session_token, requester=client_ip)
    issue_session_cookie(request, grant.session_token)
    return _to_profile_schema(grant.profile, settings)


@router.post(
    "/profiles/restore",
    name="restore_profile",
    summary="Вход по коду восстановления",
    description="Лимит — 5 попыток за 15 минут с одного IP.",
    response_model=Profile,
    responses=error_responses(
        ErrorCode.INVALID_RECOVERY_CODE, ErrorCode.VALIDATION_ERROR, ErrorCode.RATE_LIMITED
    ),
)
async def restore_profile(
    body: RestoreRequest,
    request: Request,
    session_token: OptionalSessionToken,
    client_ip: ClientIp,
    profiles: Profiles,
    settings: AppSettings,
) -> Profile:
    grant = await profiles.restore(body.code, requester=client_ip, replaced_session=session_token)
    issue_session_cookie(request, grant.session_token)
    return _to_profile_schema(grant.profile, settings)


@router.delete(
    "/me",
    name="delete_me",
    summary="Удалить все мои данные",
    description="Удаляет профиль, записи и историю диалога; cookie сбрасывается.",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_me(
    request: Request, session_token: OptionalSessionToken, profiles: Profiles
) -> None:
    await profiles.delete_profile(session_token)
    revoke_session_cookie(request)


def _to_profile_schema(profile: ProfileCard, settings: Settings) -> Profile:
    """Профиль в формате контракта со ссылкой подписки на календарь."""
    return Profile(
        id=profile.id,
        created_at=profile.created_at,
        timezone=PROFILE_TIMEZONE,
        events_count=profile.events_count,
        calendar_subscription_url=(
            f"webcal://{settings.public_host}/api/calendar/{profile.calendar_token}.ics"
        ),
        recovery_code=profile.recovery_code,
    )
