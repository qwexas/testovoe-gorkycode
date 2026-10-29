"""Зависимости FastAPI: сервисы приложения, транзакция, текущий профиль, IP клиента."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie

from app.api.errors import error_responses
from app.api.session_cookie import SESSION_COOKIE_NAME
from app.config import Settings
from app.core.admission import DialogAdmission, SpeechAdmission
from app.core.calendar import CalendarExport, SubscriptionThrottle
from app.core.dialog.service import DialogDependencies, DialogService, MessageThrottle
from app.core.errors import ErrorCode, SessionRequiredError
from app.core.events import EventService
from app.core.health import DependencyProbes
from app.core.history import SeedHistoryLoader
from app.core.profiles import ProfileCard, ProfileOnboarding, ProfileService
from app.core.recovery import RecoveryCodes
from app.core.search import SearchService
from app.core.speech import SpeechSynthesis, SynthesisThrottle
from app.nlu.interfaces import IntentParser
from app.storage.database import Database, UnitOfWork
from app.voice.interfaces import SpeechToText, TextToSpeech

UNKNOWN_CLIENT = "unknown"

session_cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="ProfileSession",
    description=(
        "Существующая сессия анонимного профиля. Без действующей cookie — 401 session_required. "
        "Профиль создаётся только явным POST /api/profiles; вход — POST /api/profiles/restore."
    ),
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class AppServices:
    """Долгоживущие объекты приложения; собираются в `app.factory.create_app`."""

    settings: Settings
    database: Database
    recovery_codes: RecoveryCodes
    profile_onboarding: ProfileOnboarding
    search: SearchService
    history_loader: SeedHistoryLoader
    intent_parser: IntentParser
    message_throttle: MessageThrottle
    speech_to_text: SpeechToText
    text_to_speech: TextToSpeech
    synthesis_throttle: SynthesisThrottle
    subscription_throttle: SubscriptionThrottle
    probes: DependencyProbes
    dialog_admission: DialogAdmission
    speech_admission: SpeechAdmission


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
    return ProfileService(storage, services.recovery_codes, services.profile_onboarding)


Profiles = Annotated[ProfileService, Depends(get_profile_service)]


def get_event_service(storage: Storage, services: Services) -> EventService:
    """Сервис записей в транзакции текущего запроса."""
    return EventService(storage, services.search)


Events = Annotated[EventService, Depends(get_event_service)]


def get_dialog_service(storage: Storage, services: Services) -> DialogService:
    """Сервис диалога в транзакции текущего запроса."""
    dependencies = DialogDependencies(
        parser=services.intent_parser,
        search=services.search,
        throttle=services.message_throttle,
        speech=services.speech_to_text,
        admission=services.dialog_admission,
    )
    return DialogService(storage, dependencies)


Dialog = Annotated[DialogService, Depends(get_dialog_service)]


def get_speech_synthesis(services: Services) -> SpeechSynthesis:
    """Озвучка ответов с лимитами на профиль, IP и общую очередь."""
    return SpeechSynthesis(
        services.text_to_speech, services.synthesis_throttle, services.speech_admission
    )


Synthesis = Annotated[SpeechSynthesis, Depends(get_speech_synthesis)]


def get_calendar_export(storage: Storage, services: Services) -> CalendarExport:
    """Экспорт календаря в транзакции текущего запроса."""
    return CalendarExport(storage, services.subscription_throttle)


CalendarFeed = Annotated[CalendarExport, Depends(get_calendar_export)]
SessionToken = Annotated[str | None, Security(session_cookie_scheme)]


def optional_session_token(request: Request) -> str | None:
    """Старая cookie для переключения/удаления; не объявляет обязательную авторизацию."""
    return request.cookies.get(SESSION_COOKIE_NAME)


OptionalSessionToken = Annotated[str | None, Depends(optional_session_token)]


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


async def get_current_profile(
    session_token: SessionToken,
    profiles: Profiles,
    storage: Storage,
) -> ProfileCard:
    """Только проверка существующей сессии; никаких созданий, seed и новых cookie.

    После проверки транзакция закрывается: соединение с БД возвращается в пул и не
    простаивает, пока маршрут ждёт LLM, распознавание или озвучку.
    """
    profile = await profiles.find_by_session(session_token)
    if profile is None:
        raise SessionRequiredError()
    await storage.commit()
    return profile


CurrentProfile = Annotated[ProfileCard, Depends(get_current_profile)]
CURRENT_PROFILE_RESPONSES = error_responses(ErrorCode.SESSION_REQUIRED)
"""Ответы маршрутов с `CurrentProfile`: отсутствующая или недействительная сессия."""
