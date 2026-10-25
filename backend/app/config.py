"""Настройки приложения из переменных окружения и корневого `.env`."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"

MIN_APP_SECRET_LENGTH = 32


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

    @property
    def public_host(self) -> str:
        """Хост (с портом, если он указан) из `PUBLIC_BASE_URL`."""
        return urlsplit(str(self.public_base_url)).netloc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Настройки процесса; читаются один раз."""
    return Settings()
