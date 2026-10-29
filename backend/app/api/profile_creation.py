"""Защита явного создания от браузерных межсайтовых запросов, не от прямых ботов."""

from typing import Annotated

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.api.dependencies import AppSettings
from app.core.errors import ForbiddenError

PROFILE_CREATION_HEADER = "X-Gorky-Client"
PROFILE_CREATION_MARKER = "web"
creation_header = APIKeyHeader(
    name=PROFILE_CREATION_HEADER,
    scheme_name="ProfileCreation",
    description=(
        "Обязательное значение web. При наличии Origin он проверяется по PROFILE_CREATION_ORIGINS."
    ),
    auto_error=False,
)


def require_profile_creation(
    request: Request,
    settings: AppSettings,
    marker: Annotated[str | None, Security(creation_header)],
) -> None:
    """HTML-форма не задаёт этот заголовок, чужой fetch требует запрещённого CORS preflight.

    Origin сверяется только с конфигурацией. Отсутствующий Origin допустим для CLI;
    заголовок всё равно обязателен. Host и forwarded-заголовки не являются источником доверия.
    """
    origins = request.headers.getlist("origin")
    if (
        marker != PROFILE_CREATION_MARKER
        or request.headers.get("sec-fetch-site") == "cross-site"
        or (origins and (len(origins) != 1 or origins[0] not in settings.profile_creation_origins))
    ):
        raise ForbiddenError()
