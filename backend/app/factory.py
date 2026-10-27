"""Сборка приложения FastAPI: настройки, сервисы, ошибки, cookie, маршруты."""

import asyncio
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
from app.config import LLMBackend, SearchBackend, Settings, VoiceBackend, get_settings
from app.core.calendar import SubscriptionThrottle
from app.core.dialog.service import MessageThrottle
from app.core.enums import ServiceStatus
from app.core.errors import SpeechToTextUnavailableError, TextToSpeechUnavailableError
from app.core.health import DependencyProbes, StatusProbe
from app.core.history import CsvProfileHistory, SeedHistoryLoader
from app.core.history_source import HistoryEntry, read_history_file
from app.core.profiles import ProfileOnboarding
from app.core.recovery import RecoveryCodes
from app.core.search import SearchService
from app.core.speech import SynthesisThrottle
from app.llm.errors import LLMUnavailableError
from app.nlu.interfaces import DialogContext, Intent, IntentParser
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer, SimilarityRanker
from app.storage.database import Database
from app.voice.interfaces import AudioClip, SpeechToText, TextToSpeech

API_TITLE = "Горький API"
API_DESCRIPTION = "Голосовой ассистент задач и встреч."

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; без аргумента настройки читаются из окружения и `.env`."""
    settings = settings or get_settings()
    language = _build_language(settings)
    voice = _build_voice(settings)
    services = _build_services(settings, language, voice)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if services.settings.load_history_on_startup:
            async with services.database.unit_of_work() as storage:
                await services.history_loader.ensure_loaded(storage)
        warm_ups = _warm_up_in_background(voice.speech_to_text, voice.text_to_speech)
        yield
        for task in warm_ups:
            task.cancel()
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


@dataclass(frozen=True, slots=True)
class _VoiceServices:
    """Распознавание и синтез речи и их проверки для `/api/health` (`None` — голос выключен)."""

    speech_to_text: SpeechToText
    text_to_speech: TextToSpeech
    stt_probe: StatusProbe | None = None
    tts_probe: StatusProbe | None = None


class _UnavailableSpeechToText:
    """Распознавание без модели: любая запись — 503 `stt_unavailable`."""

    async def transcribe(self, audio: AudioClip) -> str:
        raise SpeechToTextUnavailableError()

    async def check(self) -> ServiceStatus:
        return ServiceStatus.FAIL


class _UnavailableTextToSpeech:
    """Синтез без модели: любая озвучка — 503 `tts_unavailable`, голосов нет."""

    @property
    def voices(self) -> Sequence[str]:
        return ()

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        raise TextToSpeechUnavailableError()

    async def check(self) -> ServiceStatus:
        return ServiceStatus.FAIL


def _build_voice(settings: Settings) -> _VoiceServices:
    """Единственное место, где выбираются модели речи (`VOICE_BACKEND`).

    Если модулей Whisper / Silero ещё нет или модель не создаётся, приложение
    работает, а `/api/voice` и `/api/tts` отвечают 503 — так же, как при сбое модели;
    в `/api/health` такая модель — `fail`. При `disabled` проверки — `unknown`.
    """
    if settings.voice_backend is VoiceBackend.DISABLED:
        return _VoiceServices(_UnavailableSpeechToText(), _UnavailableTextToSpeech())
    speech_to_text: SpeechToText = _model_or_unavailable(
        _whisper_speech_to_text, _UnavailableSpeechToText, "/api/voice"
    )
    text_to_speech: TextToSpeech = _model_or_unavailable(
        _silero_text_to_speech, _UnavailableTextToSpeech, "/api/tts"
    )
    return _VoiceServices(
        speech_to_text, text_to_speech, stt_probe=speech_to_text, tts_probe=text_to_speech
    )


def _warm_up_in_background(*models: object) -> list[asyncio.Task[None]]:
    """Грузит модели речи в фоне сразу после старта, не задерживая готовность API.

    Без прогрева Whisper и Silero грузятся на первой реплике (минуты при холодном кэше).
    `warm_up()` есть у настоящих моделей и сам решает, включён ли прогрев (`*_WARM_UP_ON_STARTUP`),
    и никогда не бросает исключений; у заглушек его нет.
    """
    tasks = []
    for model in models:
        warm_up = getattr(model, "warm_up", None)
        if callable(warm_up):
            tasks.append(asyncio.create_task(warm_up(), name=f"warm-up {type(model).__name__}"))
    return tasks


def _model_or_unavailable[Model](
    build: Callable[[], Model], unavailable: Callable[[], Model], endpoint: str
) -> Model:
    """Модель речи для `endpoint` или заглушка «недоступно» с предупреждением в логе."""
    try:
        return build()
    except Exception as error:  # нет модуля, зависимости или настроек — приложение работает
        logger.warning("Модель речи для %s недоступна (%r): он отвечает 503", endpoint, error)
        return unavailable()


def _whisper_speech_to_text() -> SpeechToText:
    """faster-whisper; импорт внутри — модуль может ещё отсутствовать. Модель грузится лениво."""
    from app.voice.whisper import WhisperSpeechToText  # type: ignore[import-not-found,unused-ignore]

    speech_to_text: SpeechToText = WhisperSpeechToText()
    return speech_to_text


def _silero_text_to_speech() -> TextToSpeech:
    """Silero TTS; импорт внутри — модуль может ещё отсутствовать. Модель грузится лениво."""
    from app.voice.silero import SileroTextToSpeech  # type: ignore[import-not-found,unused-ignore]

    text_to_speech: TextToSpeech = SileroTextToSpeech()
    return text_to_speech


def _build_services(
    settings: Settings, language: _LanguageServices, voice: _VoiceServices
) -> AppServices:
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
        speech_to_text=voice.speech_to_text,
        text_to_speech=voice.text_to_speech,
        synthesis_throttle=SynthesisThrottle(),
        subscription_throttle=SubscriptionThrottle(),
        probes=DependencyProbes(llm=language.probe, stt=voice.stt_probe, tts=voice.tts_probe),
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
