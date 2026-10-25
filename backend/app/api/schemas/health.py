"""Схемы проверки живости."""

from typing import Literal

from app.api.schemas.base import ResponseModel
from app.core.enums import ServiceStatus
from app.core.health import DatabaseStatus


class HealthChecks(ResponseModel):
    """Состояние зависимостей."""

    db: DatabaseStatus
    llm: ServiceStatus
    stt: ServiceStatus
    tts: ServiceStatus


class HealthResponse(ResponseModel):
    """Ответ `GET /api/health`."""

    status: Literal["ok"]
    version: str
    checks: HealthChecks
