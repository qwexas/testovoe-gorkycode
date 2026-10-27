"""Настройки приложения из переменных окружения и корневого `.env`."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"

MIN_APP_SECRET_LENGTH = 32
DEFAULT_EMBEDDING_MODEL = "deepvk/USER-bge-m3"


class SearchBackend(StrEnum):
    """Чем считать векторы, леммы и ранжирование поиска."""

    REAL = "real"
    """Модель эмбеддингов, pymorphy3 и гибридное ранжирование из `app.search`."""
    PLACEHOLDER = "placeholder"
    """Быстрые заглушки без модели из `app.search.placeholders` — для тестов."""


class LLMBackend(StrEnum):
    """Чем разбирать реплики пользователя."""

    GIGACHAT = "gigachat"
    """GigaChat API; ключ и модель — в переменных `GIGACHAT_*` (`app.llm.settings`)."""
    DISABLED = "disabled"
    """Без языковой модели: `/api/chat` отвечает 503 `llm_unavailable` — для тестов."""


class VoiceBackend(StrEnum):
    """Чем распознавать и озвучивать речь."""

    REAL = "real"
    """Whisper и Silero из `app.voice`; если модели нет — `/api/voice` и `/api/tts` отвечают 503."""
    DISABLED = "disabled"
    """Без моделей речи: `/api/voice` и `/api/tts` отвечают 503 — для тестов и выгрузки OpenAPI."""


class Settings(BaseSettings):
    """Конфигурация бэкенда.

    Значения берутся из окружения, затем из корневого `.env` репозитория
    (в контейнере файла нет — переменные приходят из docker-compose).
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(description="SQLAlchemy URL: postgresql+asyncpg://…")
    app_secret: SecretStr = Field(
        min_length=MIN_APP_SECRET_LENGTH,
        description="Ключ HMAC для кодов восстановления",
    )
    cookie_secure: bool = Field(default=True, description="Флаг Secure у cookie профиля")
    public_base_url: HttpUrl = Field(
        default=HttpUrl("https://voice.wexasas.online"),
        description="Публичный адрес сервиса — из него строится ссылка подписки на календарь",
    )
    search_backend: SearchBackend = Field(
        default=SearchBackend.REAL,
        description="`real` — модель и морфология; `placeholder` — заглушки без модели",
    )
    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL,
        description="Модель sentence-transformers размерности 1024",
    )
    embedding_cache_dir: Path | None = Field(
        default=None,
        description="Каталог весов модели; пусто — стандартный кэш Hugging Face (`HF_HOME`)",
    )
    llm_backend: LLMBackend = Field(
        default=LLMBackend.GIGACHAT,
        description="`gigachat` — разбор реплик GigaChat; `disabled` — без LLM (тесты)",
    )
    voice_backend: VoiceBackend = Field(
        default=VoiceBackend.REAL,
        description="`real` — Whisper и Silero; `disabled` — без моделей речи (тесты)",
    )
    load_history_on_startup: bool = Field(
        default=True,
        description="Заполнять `seed_events` при старте; выключают только тесты без базы",
    )

    @property
    def public_host(self) -> str:
        """Хост (с портом, если он указан) из `PUBLIC_BASE_URL`."""
        return urlsplit(str(self.public_base_url)).netloc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Настройки процесса; читаются один раз."""
    return Settings()
