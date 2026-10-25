"""Зависимости FastAPI: сервисы приложения, транзакция, текущий профиль, IP клиента."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie

from app.api.session_cookie import SESSION_COOKIE_NAME, issue_session_cookie
from app.config import Settings
from app.core.history import ProfileHistorySeeder
from app.core.profiles import ProfileCard, ProfileService
from app.core.recovery import RecoveryCodes
from app.storage.database import Database, UnitOfWork

UNKNOWN_CLIENT = "unknown"

session_cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="ProfileSession",
    description=(
        "Анонимный профиль. Если cookie нет или она недействительна, "
        "эндпоинт создаёт новый профиль и ставит cookie сам."
    ),
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class AppServices:
    """Долгоживущие объекты приложения; собираются в `app.factory.create_app`."""

    settings: Settings
    database: Database
    recovery_codes: RecoveryCodes
    profile_history: ProfileHistorySeeder


def get_services(request: Request) -> AppServices:
    """Сервисы, сохранённые в `app.state` при создании приложения."""
    services: AppServices = request.app.state.services
    return services


Services = Annotated[AppServices, Depends(get_services)]


def get_settings(services: Services) -> Settings:
    """Настройки приложения."""
    return services.settings


AppSettings = Annotated[Settings, Depends(get_settings)]


async def get_storage(services: Services) -> AsyncIterator[UnitOfWork]:
    """Единица работы на время запроса; незафиксированное откатывается."""
    async with services.database.unit_of_work() as storage:
        yield storage


Storage = Annotated[UnitOfWork, Depends(get_storage)]


def get_profile_service(storage: Storage, services: Services) -> ProfileService:
    """Сервис профилей в транзакции текущего запроса."""
    return ProfileService(storage, services.recovery_codes, services.profile_history)


Profiles = Annotated[ProfileService, Depends(get_profile_service)]
SessionToken = Annotated[str | None, Security(session_cookie_scheme)]


async def get_current_profile(
    request: Request, session_token: SessionToken, profiles: Profiles
) -> ProfileCard:
    """Профиль из cookie; если cookie нет или она недействительна — новый профиль."""
    profile = await profiles.find_by_session(session_token)
    if profile is not None:
        return profile
    grant = await profiles.create_profile(replaced_session=session_token)
    issue_session_cookie(request, grant.session_token)
    return grant.profile


CurrentProfile = Annotated[ProfileCard, Depends(get_current_profile)]


def get_client_ip(request: Request) -> str:
    """IP клиента: `CF-Connecting-IP`, затем первый адрес `X-Forwarded-For`, затем сокет.

    Заголовкам можно доверять: наружу сервис открыт только через nginx на 127.0.0.1.
    """
    cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare_ip:
        return cloudflare_ip
    forwarded_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded_ip:
        return forwarded_ip
    return request.client.host if request.client else UNKNOWN_CLIENT


ClientIp = Annotated[str, Depends(get_client_ip)]
