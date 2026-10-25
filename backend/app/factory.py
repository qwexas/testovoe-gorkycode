"""Сборка приложения FastAPI: настройки, сервисы, ошибки, cookie, маршруты."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app import __version__
from app.api.dependencies import AppServices
from app.api.errors import install_error_handlers
from app.api.router import api_router
from app.api.session_cookie import SessionCookieMiddleware
from app.config import Settings, get_settings
from app.core.history import EmptyProfileHistory
from app.core.recovery import RecoveryCodes
from app.storage.database import Database

API_TITLE = "Горький API"
API_DESCRIPTION = (
    "Голосовой ассистент задач и встреч. Человекочитаемый контракт — `docs/api-contract.md`."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; без аргумента настройки читаются из окружения и `.env`."""
    services = _build_services(settings or get_settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await services.database.dispose()

    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    app.state.services = services
    install_error_handlers(app)
    app.add_middleware(SessionCookieMiddleware, cookie_secure=services.settings.cookie_secure)
    app.include_router(api_router)
    return app


def _build_services(settings: Settings) -> AppServices:
    return AppServices(
        settings=settings,
        database=Database(settings.database_url),
        recovery_codes=RecoveryCodes(settings.app_secret.get_secret_value().encode()),
        profile_history=EmptyProfileHistory(),
    )


def _operation_id(route: APIRoute) -> str:
    return route.name
