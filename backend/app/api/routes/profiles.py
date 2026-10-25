"""Анонимный профиль: текущий, новый, вход по коду, удаление всех данных."""

from fastapi import APIRouter, Request, status

from app.api.dependencies import AppSettings, ClientIp, CurrentProfile, Profiles, SessionToken
from app.api.errors import error_responses
from app.api.schemas.profiles import Profile, RestoreRequest
from app.api.session_cookie import issue_session_cookie, revoke_session_cookie
from app.config import Settings
from app.core.errors import ErrorCode
from app.core.profiles import PROFILE_TIMEZONE, ProfileCard

router = APIRouter(tags=["profile"])


@router.get(
    "/me",
    name="get_me",
    summary="Текущий профиль",
    description="Если профиля нет, создаёт его — тогда `recovery_code` заполнен.",
    response_model=Profile,
)
async def get_me(profile: CurrentProfile, settings: AppSettings) -> Profile:
    return _to_profile_schema(profile, settings)


@router.post(
    "/profiles",
    name="create_profile",
    summary="Новый профиль",
    description="Создаёт профиль и переключает на него cookie этого устройства.",
    status_code=status.HTTP_201_CREATED,
    response_model=Profile,
)
async def create_profile(
    request: Request, session_token: SessionToken, profiles: Profiles, settings: AppSettings
) -> Profile:
    grant = await profiles.create_profile(replaced_session=session_token)
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
    session_token: SessionToken,
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
async def delete_me(request: Request, session_token: SessionToken, profiles: Profiles) -> None:
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
