"""настройки GigaChat из переменных окружения `GIGACHAT_*` и корневого `.env`."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ENV_FILE, REPOSITORY_ROOT

DEFAULT_FALLBACK_MODEL = "GigaChat-3-Ultra"
"""запасная модель на случай пустого или некорректного ответа основной."""
DEFAULT_MODEL = "GigaChat-2-Pro"
DEFAULT_SCOPE = "GIGACHAT_API_PERS"
DEFAULT_BASE_URL = "https://api.giga.chat/v1"
DEFAULT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BUNDLED_ROOT_CA = REPOSITORY_ROOT / "infra" / "certs" / "russian_trusted_root_ca.pem"
"""корневой сертификат Минцифры в репозитории. В Docker его нет: он в системном хранилище."""


def _bundled_root_ca() -> Path | None:
    return BUNDLED_ROOT_CA if BUNDLED_ROOT_CA.is_file() else None


class GigaChatSettings(BaseSettings):
    """подключение к GigaChat API.

    Читаются переменные с префиксом `GIGACHAT_`, затем корневой `.env` (в контейнере
    переменные приходят из docker-compose). Ключ хранится как `SecretStr` и не попадает
    ни в `repr`, ни в логи.
    """

    model_config = SettingsConfigDict(
        env_prefix="GIGACHAT_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    credentials: SecretStr | None = Field(
        default=None, description="Ключ авторизации из личного кабинета developers.sber.ru"
    )
    scope: str = Field(default=DEFAULT_SCOPE, description="`GIGACHAT_API_PERS` для физлиц")
    model: str = Field(default=DEFAULT_MODEL, description="Модель для разбора реплик")
    fallback_model: str | None = Field(
        default=DEFAULT_FALLBACK_MODEL,
        description=(
            "Модель для повтора, если основная вернула пустой ответ или ответ не по схеме. "
            "GigaChat-2-Pro изредка молчит на новой команде в ответ на уточнение"
        ),
    )
    base_url: str = Field(default=DEFAULT_BASE_URL)
    auth_url: str = Field(default=DEFAULT_AUTH_URL)
    root_ca_file: Path | None = Field(
        default_factory=_bundled_root_ca,
        description=(
            "Дополнительный корневой сертификат (Минцифры). Пусто — только системное "
            "хранилище и certifi: так в Docker, где сертификат добавлен в систему"
        ),
    )
    request_timeout_seconds: float = Field(default=20.0, gt=0, description="Таймаут запроса")
    temperature: float = Field(default=0.01, ge=0, description="Низкая — разбор детерминирован")

    @property
    def is_configured(self) -> bool:
        """задан ли ключ: без него запросы к модели не отправляются."""
        return self.credentials is not None and bool(self.credentials.get_secret_value())
