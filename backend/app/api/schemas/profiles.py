"""схемы профиля."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.api.schemas.base import RequestModel, ResponseModel

RECOVERY_CODE_MAX_LENGTH = 200


class Profile(ResponseModel):
    """Анонимный профиль."""

    id: UUID
    created_at: datetime
    timezone: str = Field(description="Всегда `Europe/Moscow`")
    events_count: int
    calendar_subscription_url: str = Field(
        description="Ссылка подписки: `webcal://…/api/calendar/{token}.ics`"
    )
    recovery_code: str | None = Field(
        description="Код восстановления; только в ответе на создание профиля, иначе `null`",
        examples=["сирень-лиса-кедр-4821"],
    )


class RestoreRequest(RequestModel):
    """Вход в профиль по коду восстановления."""

    code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=RECOVERY_CODE_MAX_LENGTH),
    ] = Field(examples=["сирень-лиса-кедр-4821"])
