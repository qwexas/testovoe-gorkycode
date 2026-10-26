"""Сборка приложения FastAPI: настройки, сервисы, ошибки, cookie, маршруты."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app import __version__
from app.api.dependencies import AppServices
from app.api.errors import install_error_handlers
from app.api.router import api_router
from app.api.session_cookie import SessionCookieMiddleware
from app.config import LLMBackend, SearchBackend, Settings, get_settings
from app.core.dialog.service import MessageThrottle
from app.core.health import StatusProbe
from app.core.history import CsvProfileHistory, SeedHistoryLoader
from app.core.history_source import HistoryEntry, read_history_file
from app.core.profiles import ProfileOnboarding
from app.core.recovery import RecoveryCodes
from app.core.search import SearchService
from app.llm.errors import LLMUnavailableError
from app.nlu.interfaces import DialogContext, Intent, IntentParser
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer, SimilarityRanker
from app.storage.database import Database

API_TITLE = "Горький API"
API_DESCRIPTION = (
    "Голосовой ассистент задач и встреч. Человекочитаемый контракт — `docs/api-contract.md`."
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; без аргумента настройки читаются из окружения и `.env`."""
    settings = settings or get_settings()
    language = _build_language(settings)
    services = _build_services(settings, language)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if services.settings.load_history_on_startup:
            async with services.database.unit_of_work() as storage:
                await services.history_loader.ensure_loaded(storage)
        yield
        await services.database.dispose()
        await language.close()

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


@dataclass(frozen=True, slots=True)
class _LanguageServices:
    """Разбор реплик, проверка LLM для `/api/health` (`None` — LLM не подключена)
    и закрытие соединений клиента при остановке приложения."""

    parser: IntentParser
    probe: StatusProbe | None = None
    closer: Callable[[], Awaitable[None]] | None = None

    async def close(self) -> None:
        """Закрывает соединения клиента LLM, если он есть."""
        if self.closer is not None:
            await self.closer()


class _UnavailableIntentParser:
    """Разбор без языковой модели: любая реплика — 503 `llm_unavailable`."""

    async def parse(self, text: str, context: DialogContext) -> Intent:
        raise LLMUnavailableError()


def _build_services(settings: Settings, language: _LanguageServices) -> AppServices:
    history = read_history_file()
    search = _build_search(settings, history)
    return AppServices(
        settings=settings,
        database=Database(settings.database_url),
        recovery_codes=RecoveryCodes(settings.app_secret.get_secret_value().encode()),
        profile_onboarding=ProfileOnboarding(CsvProfileHistory()),
        search=search,
        history_loader=SeedHistoryLoader(search, history),
        intent_parser=language.parser,
        message_throttle=MessageThrottle(),
        llm_probe=language.probe,
    )


def _build_language(settings: Settings) -> _LanguageServices:
    """Единственное место, где выбирается разбор реплик (`LLM_BACKEND`).

    Если модулей GigaChat ещё нет или ключ не задан, приложение работает, а
    `/api/chat` отвечает 503 `llm_unavailable` — так же, как при сбое GigaChat.
    """
    if settings.llm_backend is LLMBackend.DISABLED:
        return _LanguageServices(_UnavailableIntentParser())
    try:
        return _gigachat_language()
    except ImportError as error:
        logger.warning("Разбор реплик недоступен (%s): /api/chat отвечает 503", error)
        return _LanguageServices(_UnavailableIntentParser())


def _gigachat_language() -> _LanguageServices:
    """GigaChat-клиент и LLM-парсер; импорт внутри — модули могут ещё отсутствовать."""
    from app.llm.gigachat import GigaChatClient
    from app.llm.settings import GigaChatSettings
    from app.nlu.parser import LLMIntentParser

    llm_settings = GigaChatSettings()
    if not llm_settings.is_configured:
        logger.warning("GIGACHAT_CREDENTIALS не задан: /api/chat отвечает 503 llm_unavailable")
        return _LanguageServices(_UnavailableIntentParser())
    client = GigaChatClient.from_settings(llm_settings)
    return _LanguageServices(parser=LLMIntentParser(client), probe=client, closer=client.aclose)


def _build_search(settings: Settings, history: Sequence[HistoryEntry]) -> SearchService:
    """Единственное место, где выбираются реализации поиска (`SEARCH_BACKEND`)."""
    if settings.search_backend is SearchBackend.REAL:
        try:
            return _model_search(settings, history)
        except ImportError as error:
            logger.warning(
                "Поиск по модели недоступен (%s): работают заглушки app.search.placeholders",
                error,
            )
    return SearchService(HashingEmbedder(), LowercaseLemmatizer(), SimilarityRanker())


def _model_search(settings: Settings, history: Sequence[HistoryEntry]) -> SearchService:
    """Модель эмбеддингов, pymorphy3 и гибридное ранжирование.

    Импорт внутри функции: если модулей или их зависимостей нет, `_build_search`
    переключается на заглушки, а не роняет приложение. Модель грузится лениво —
    при заполнении `seed_events` на старте.
    """
    from app.search.embedder import SentenceTransformerEmbedder
    from app.search.lemmas import MorphLemmatizer
    from app.search.ranking import HybridRanker, LemmaStatistics

    lemmatizer = MorphLemmatizer()
    statistics = LemmaStatistics.from_documents(lemmatizer.lemmas(entry.title) for entry in history)
    return SearchService(
        SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_cache_dir),
        lemmatizer,
        HybridRanker(statistics, names=lemmatizer),
    )


def _operation_id(route: APIRoute) -> str:
    return route.name
